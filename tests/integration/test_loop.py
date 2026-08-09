from coding_agent_harness.core.loop import AgentLoop, MAX_HISTORY_MESSAGES
from coding_agent_harness.llm.base import Message
from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.memory.store import Memory
from coding_agent_harness.config import load_config
from coding_agent_harness.models import WriteFile, RunTests, Stop, Respond, AssistantTurn
import yaml
import tempfile
from pathlib import Path

FIX = Path(__file__).parent.parent.parent / "fixtures" / "sample_pkg"


def _cfg(root, max_rounds=8, hard_max_rounds=60):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({
        "project_root": str(root),
        "llm": {"base_url": "x", "model": "m"},
        "guardrails": {"max_rounds": max_rounds, "hard_max_rounds": hard_max_rounds,
                       "same_category_prompt_at": 2,
                       "same_category_stop_at": 3, "no_change_stop_at": 2},
        "feedback": {"pytest_args": ["--tb=short", "-q"], "max_traceback_excerpt_lines": 8},
        "memory": {"fixes_path": str(root / "fixes.json"),
                   "conventions_path": str(root / "conv.json"), "retrieve_top_k": 3},
    }, f)
    f.close()
    return load_config(f.name)


def test_loop_red_to_green(tmp_path):
    import shutil
    shutil.copytree(FIX, tmp_path / "ws", dirs_exist_ok=True)
    ws = tmp_path / "ws"
    mock = MockLLMClient([
        {"when": "round 1", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+2\n"), "intent": "我先改返回值"},
        {"when": "round 2", "action": RunTests(), "intent": "验证修复"},
        # `round 4` 须排在 `feedback.category` 之前:round 3 的 WriteFile 不产生
        # feedback,last_category 仍为 AssertionFailure(brief 追踪要求),故 round 4
        # 若排在后会被反馈分支首匹配抢占;前置后 round 3(=3≠4)仍落反馈分支,
        # 保留"反馈闭环使 agent 改变下一步"演示,round 4 才能命中 RunTests→PASS。
        {"when": "round 4", "action": RunTests(), "intent": "再验证"},
        {"when": "feedback.category == AssertionFailure", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+1\n"), "intent": "上次断言失败,改 off-by-one"},
        {"when": "feedback.status == PASS", "action": Stop("done"), "intent": "测试全绿,完成"},
    ])
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    loop = AgentLoop(llm=mock, config=cfg, memory=mem)
    result = loop.run(task="修 add 的 bug", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "stopped"  # PASS 后 agent 显式 Stop(不再自动判 success)
    assert any(s.turn.intent == "上次断言失败,改 off-by-one" for s in result.steps)


def test_conversation_history_trimmed(tmp_path):
    """长会话下对话历史被截断到 MAX_HISTORY_MESSAGES 上限,保留最新消息。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    loop = AgentLoop(llm=MockLLMClient([]), config=cfg, memory=mem)
    n = MAX_HISTORY_MESSAGES + 20  # 超出上限
    for i in range(n):
        loop._append_history(Message("user", f"msg-{i}"))
    assert len(loop.conversation_history) == MAX_HISTORY_MESSAGES
    # 保留最新:最早被丢弃的应是第 n - MAX 条
    assert loop.conversation_history[0].content == f"msg-{n - MAX_HISTORY_MESSAGES}"
    assert loop.conversation_history[-1].content == f"msg-{n - 1}"
    # 未超上限时不截断
    loop.conversation_history = []
    for i in range(5):
        loop._append_history(Message("user", f"m{i}"))
    assert len(loop.conversation_history) == 5


class _RecordingLLM:
    """记录每次 complete 收到的 messages,验证上下文组织顺序。"""
    def __init__(self):
        self.calls = []
    def complete(self, messages, tools, state):
        self.calls.append(list(messages))
        n = len(self.calls)
        if n == 1:
            return AssistantTurn(action=Respond("你好,我是 agent"), intent="回复", raw="x")
        return AssistantTurn(action=Stop("done"), intent="完成", raw="x")


def test_message_order_history_before_new_task(tmp_path):
    """第二轮起消息顺序应为 [system, *历史, user(新任务), *反馈/提示]:
    新任务必须排在历史之后(时间顺序),否则 LLM 把最新指令夹在历史中间。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    llm = _RecordingLLM()
    loop = AgentLoop(llm=llm, config=cfg, memory=mem)
    loop.run(task="修 bug", ts_provider=lambda: "2026-07-22T00:00:00")
    # 第 1 轮:Respond;第 2 轮:Stop
    assert len(llm.calls) >= 2
    second = llm.calls[1]
    roles = [m.role for m in second]
    # system 开头,随后是历史(assistant),新任务(user)在历史之后
    assert roles[0] == "system"
    assert "assistant" in roles
    task_idx = roles.index("user")
    assert any(m.role == "assistant" for m in second[:task_idx]), "新任务之前应已有历史(assistant)"
    assert second[task_idx].content == "修 bug"


def test_loop_respond_twice_then_stop_via_prompt(tmp_path):
    """连续 2 次 Respond 不再自动停机(放宽到 3 次,防止误杀分段回复);
    第 3 次仍触发自动停机。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    mock = MockLLMClient([
        {"when": "round 1", "action": Respond("第一段说明"), "intent": "回复"},
        {"when": "round 2", "action": Respond("第二段补充"), "intent": "回复"},
        {"when": "round 3", "action": Respond("第三段"), "intent": "回复"},
    ])
    loop = AgentLoop(llm=mock, config=cfg, memory=mem)
    result = loop.run(task="随便聊聊", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "stopped"
    responds = [s for s in result.steps if isinstance(s.turn.action, Respond)]
    assert len(responds) == 3, "连续 2 次 Respond 不应自动停机(放宽到 3 次)"


def test_loop_stop_trivial_reason_fallback_response(tmp_path):
    """LLM 直接 stop 且 reason 为 done/空(无文字回复)→ 发兜底 response,
    防止"做了事但用户看不到任何回答"。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    events = []
    mock = MockLLMClient([
        {"when": "always", "action": Stop("done"), "intent": "完成"},
    ])
    loop = AgentLoop(llm=mock, config=cfg, memory=mem, on_event=events.append)
    result = loop.run(task="修 bug", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "stopped"
    texts = [e["text"] for e in events if e["type"] == "response"]
    assert texts, "stop 无文字时应发兜底 response,否则用户看不到回答"
    assert "完成" in texts[0]


def test_loop_stop_reason_emitted_as_response(tmp_path):
    """Stop 带非 trivial reason → 直接发 response 事件展示总结(不重复兜底)。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    events = []
    mock = MockLLMClient([
        {"when": "always", "action": Stop("修复了 calc.py,测试通过"), "intent": "完成"},
    ])
    loop = AgentLoop(llm=mock, config=cfg, memory=mem, on_event=events.append)
    loop.run(task="修 bug", ts_provider=lambda: "2026-07-22T00:00:00")
    texts = [e["text"] for e in events if e["type"] == "response"]
    assert texts == ["修复了 calc.py,测试通过"]


def test_loop_run_tests_feedback_compact_feed(tmp_path):
    """RunTests 回灌用一行摘要(fb 结果),详情由 feedback 消息提供——避免全文冗余。"""
    import shutil
    shutil.copytree(FIX, tmp_path / "ws", dirs_exist_ok=True)
    ws = tmp_path / "ws"
    mock = MockLLMClient([
        {"when": "round 1", "action": RunTests(), "intent": "验证"},
        {"when": "always", "action": Stop("done"), "intent": "完成"},
    ])
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    loop = AgentLoop(llm=mock, config=cfg, memory=mem)
    loop.run(task="修 bug", ts_provider=lambda: "2026-07-22T00:00:00")
    step_msgs = [m.content for m in loop.conversation_history
                 if m.content.startswith("[上一步]") and "RunTests" in m.content]
    assert step_msgs, "应存在 RunTests 的回灌消息"
    assert "测试结果" in step_msgs[0], "RunTests 回灌应为一行摘要,而非全文"
    assert "traceback" not in step_msgs[0].lower()


def test_loop_history_compact_old_rounds():
    """超过 MAX_FULL_STEPS 轮后,最早轮次的完整回灌压缩为一行摘要(Claude Code 式历史压缩)。"""
    from coding_agent_harness.core.loop import MAX_FULL_STEPS
    loop = AgentLoop(llm=None, config=None, memory=None)
    for i in range(MAX_FULL_STEPS + 4):
        loop._append_history(Message("user",
            f"[上一步] WriteFile: 写文件 {i}\n[结果]\n" + "x" * 400 + "\n\n提示"))
    steps = [m for m in loop.conversation_history if m.content.startswith("[上一步]")]
    compacted = [m for m in loop.conversation_history if m.content.startswith("(历史")]
    assert len(compacted) == 4, "最早的 4 轮应压缩为一行摘要"
    assert len(steps) == MAX_FULL_STEPS, "完整回灌应只保留最近 MAX_FULL_STEPS 轮"
    assert "写文件 0" in compacted[0].content, "压缩保留动作名与意图要点"
    assert "[结果]" in steps[-1].content, "最近轮次保持完整"


def test_tool_call_with_text_emits_response_then_executes(tmp_path):
    """工具调用带伴随文字(OpenAI 协议 content+tool_calls 并存)→ 先发 response
    显示文字,再执行工具。解决「只有工具调用,没有回复」。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    events = []
    from coding_agent_harness.models import ListDir
    class _T:
        def __init__(self, action, intent, text=None):
            self.action = action
            self.intent = intent
            self.text = text
    class _LLM:
        def __init__(self):
            self.n = 0
        def complete(self, messages, tools, state):
            self.n += 1
            if self.n == 1:
                return _T(ListDir("."), "查看项目结构", text="我来看看目录结构。")
            return _T(Stop("done"), "完成")
    loop = AgentLoop(llm=_LLM(), config=cfg, memory=mem, on_event=events.append)
    result = loop.run(task="列出文件内容", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "stopped"
    texts = [e["text"] for e in events if e["type"] == "response"]
    assert texts and texts[0] == "我来看看目录结构。", "工具调用前的文字应显示给用户"


def test_list_dir_then_stop_trivial_shows_result(tmp_path):
    """「列出文件」场景:agent 调 list_dir 后直接 stop("done") → 兜底显示最后
    工具结果摘要(用户直接看到文件列表),而非空泛的(任务完成)。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "calc.py").write_text("x")
    (ws / "README.md").write_text("x")
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    events = []
    from coding_agent_harness.models import ListDir
    mock = MockLLMClient([
        {"when": "round 1", "action": ListDir("."), "intent": "查看项目结构"},
        {"when": "always", "action": Stop("done"), "intent": "完成"},
    ])
    loop = AgentLoop(llm=mock, config=cfg, memory=mem, on_event=events.append)
    loop.run(task="列出文件", ts_provider=lambda: "2026-07-22T00:00:00")
    texts = [e["text"] for e in events if e["type"] == "response"]
    assert texts, "应发兜底回复"
    assert "calc.py" in texts[0], f"兜底应含文件列表摘要: {texts[0]}"


def test_max_rounds_stop_emits_fallback(tmp_path):
    """达到 max_rounds 停机且全程无任何文字 → 发中性兜底回复。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws, max_rounds=3)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    events = []
    from coding_agent_harness.models import ListDir
    mock = MockLLMClient([
        {"when": "always", "action": ListDir("."), "intent": "查看"},
    ])
    loop = AgentLoop(llm=mock, config=cfg, memory=mem, on_event=events.append)
    result = loop.run(task="列出文件", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "max_rounds"
    texts = [e["text"] for e in events if e["type"] == "response"]
    assert texts, "max_rounds 停机且无回复时应发兜底"


def test_system_prompt_mentions_round_limit(tmp_path):
    """系统提示词应告知 LLM 轮数上限,并促使其规划工具调用(避免轮次耗尽)。"""
    from coding_agent_harness.core.state import LoopState
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws, max_rounds=20)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    loop = AgentLoop(llm=MockLLMClient([]), config=cfg, memory=mem)
    msgs = loop._build_messages("任务", LoopState())
    sys_content = msgs[0].content
    assert "20" in sys_content, "系统提示词应告知轮数上限"
    assert "轮" in sys_content


def test_system_prompt_list_dir_stops_exploration(tmp_path):
    """「列出文件内容」分流应强化:回复文件名列表后 stop,不读内容/不探索子目录。"""
    from coding_agent_harness.core.state import LoopState
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    loop = AgentLoop(llm=MockLLMClient([]), config=cfg, memory=mem)
    sys_content = loop._build_messages("任务", LoopState())[0].content
    assert "列出文件" in sys_content
    assert "不要逐层多次" in sys_content or "不要深入" in sys_content, "提示词应禁止逐层重复探索"
    assert "recursive" in sys_content, "提示词应引导用 recursive 一次列出整个目录树"
    assert "shell" in sys_content and "不要" in sys_content, "提示词应告知 shell 不可用"


def test_rejected_actions_streak_prompts(tmp_path):
    """连续 3 次动作被护栏拦截 → 注入「停止尝试被拦截操作」提示(确定性可测)。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    from coding_agent_harness.models import RunShell
    class _Cap:
        def __init__(self):
            self.received = []
        def complete(self, messages, tools, state):
            self.received.append([m.content for m in messages])
            return MockLLMClient([
                {"when": "round 1", "action": RunShell("grep x"), "intent": "查找"},
                {"when": "round 2", "action": RunShell("find . -name *.java"), "intent": "查找"},
                {"when": "round 3", "action": RunShell("cat KWIC.java"), "intent": "查看"},
                {"when": "always", "action": Stop("done"), "intent": "完成"},
            ]).complete(messages, tools, state)
    cap = _Cap()
    loop = AgentLoop(llm=cap, config=cfg, memory=mem)
    result = loop.run(task="列出文件", ts_provider=lambda: "2026-07-22T00:00:00")
    # 3 次全被拒,注入提示后仍继续,最终 Stop 结束
    assert result.outcome == "stopped"
    flat = "\n".join("\n".join(c) for c in cap.received)
    assert "连续" in flat and "拦截" in flat, "应注入连续被拦截提示(第 4 轮消息)"


def test_needs_approval_fallback_tells_agent_not_to_retry(tmp_path):
    """非 HITL 下 NeedsApproval 回灌应明确「不要重复尝试该动作」。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    from coding_agent_harness.models import RunShell
    mock = MockLLMClient([
        {"when": "round 1", "action": RunShell("grep x"), "intent": "查找"},
        {"when": "always", "action": Stop("done"), "intent": "完成"},
    ])
    loop = AgentLoop(llm=mock, config=cfg, memory=mem)
    loop.run(task="列出文件", ts_provider=lambda: "2026-07-22T00:00:00")
    rejected = [m.content for m in loop.conversation_history if "需人工审批" in m.content]
    assert rejected, "应存在 NeedsApproval 的回灌消息"
    assert "不要重复尝试" in rejected[0], f"回灌应告知不要重复尝试: {rejected[0]}"


def test_loop_continues_past_max_rounds_with_warning(tmp_path):
    """超过 max_rounds(软)但未达 hard_max_rounds 时循环继续,并注入「尽快收尾」提示。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws, max_rounds=3, hard_max_rounds=8)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    from coding_agent_harness.models import ListDir
    class _Cap:
        def __init__(self):
            self.received = []
        def complete(self, messages, tools, state):
            self.received.append([m.content for m in messages])
            # 前 6 轮持续 ListDir(模拟复杂任务超过软上限),第 7 轮 stop
            return MockLLMClient([
                {"when": "round 6", "action": Stop("完成了"), "intent": "完成"},
                {"when": "always", "action": ListDir("."), "intent": "查看"},
            ]).complete(messages, tools, state)
    cap = _Cap()
    loop = AgentLoop(llm=cap, config=cfg, memory=mem)
    result = loop.run(task="任务", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "stopped", f"超过软上限应继续而非终止: {result.outcome}"
    flat = "\n".join("\n".join(c) for c in cap.received)
    assert "软上限" in flat and "已执行" in flat, "达到软上限应注入尽快收尾提示"


def test_loop_stops_at_hard_max_rounds(tmp_path):
    """达到 hard_max_rounds 仍强制终止(安全阀,防死循环)。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws, max_rounds=3, hard_max_rounds=5)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    from coding_agent_harness.models import ListDir
    mock = MockLLMClient([{"when": "always", "action": ListDir("."), "intent": "查看"}])
    loop = AgentLoop(llm=mock, config=cfg, memory=mem)
    result = loop.run(task="任务", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "max_rounds"


def test_stop_reason_redundant_not_duplicated(tmp_path):
    """最终 Stop reason 与已输出的文字重复(清单输出两遍)→ 不再重复发,
    已输出的内容就是最终答复(修复「最后回答重复输出清单与概述」)。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    events = []
    # 先 Respond 输出完整清单,再 Stop reason 又输出一遍完整清单(真实 LLM 行为)
    mock = MockLLMClient([
        {"when": "round 1", "action": Respond("文件清单:\n- calc.py\n- README.md\n概述: 计算器与说明"), "intent": "回复"},
        {"when": "always", "action": Stop("文件清单:\n- calc.py\n- README.md\n概述: 计算器与说明"), "intent": "完成"},
    ])
    loop = AgentLoop(llm=mock, config=cfg, memory=mem, on_event=events.append)
    result = loop.run(task="列出文件内容", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "stopped"
    texts = [e["text"] for e in events if e["type"] == "response"]
    # 清单只在 Respond 输出一次;Stop 的重复 reason 被去重,不再出现第二遍
    assert len(texts) == 1, f"清单不应重复输出,应只有一次: {texts}"
    assert "文件清单" in texts[0]


def test_stop_reason_summary_not_duplicated(tmp_path):
    """Stop reason 是简短总结(未与已输出重复)→ 正常发出。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    events = []
    mock = MockLLMClient([
        {"when": "round 1", "action": Respond("文件清单:\n- calc.py\n- README.md"), "intent": "回复"},
        {"when": "always", "action": Stop("已列出 2 个文件的清单"), "intent": "完成"},
    ])
    loop = AgentLoop(llm=mock, config=cfg, memory=mem, on_event=events.append)
    loop.run(task="列出文件内容", ts_provider=lambda: "2026-07-22T00:00:00")
    texts = [e["text"] for e in events if e["type"] == "response"]
    assert texts[-1] == "已列出 2 个文件的清单", "简短总结应正常发出"
