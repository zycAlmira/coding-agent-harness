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


def _cfg(root):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({
        "project_root": str(root),
        "llm": {"base_url": "x", "model": "m"},
        "guardrails": {"max_rounds": 8, "same_category_prompt_at": 2,
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
