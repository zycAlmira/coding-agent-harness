"""Agent 主循环。自实现,不寄生框架。
组织上下文 → 调 LLM → 解析动作 → 护栏 → (审批)→ 分发 → 校验 → 回灌 → 停机。"""
from __future__ import annotations
import threading
from typing import Callable
from coding_agent_harness.config import Config
from coding_agent_harness.models import (
    RunTests, Stop, ToolResult, Step, RunResult, Fix, Respond, WriteFile, ReadFile,
    AssistantTurn, Verdict, Feedback, Allow,
)
from coding_agent_harness.llm.base import LLMClient, Message, ToolSchema
from coding_agent_harness.tools.dispatch import dispatch
from coding_agent_harness.feedback.validator import Validator
from coding_agent_harness.feedback.taxonomy import strategy_hint, FailureCategory
from coding_agent_harness.guardrails.guardrail import guardrail
from coding_agent_harness.core.state import LoopState, update_after_feedback, decide_stop


# Agent 可用工具清单(JSON Schema),供真实 LLM 的 function-calling 使用。
# 参数名与 openai_compat._ACTION_BUILDERS 的 key 对齐。
_INTENT_PROP = {"intent": {"type": "string", "description": "执行此动作的理由(一句话)"}}

_AGENT_TOOLS = [
    ToolSchema("read_file", "读取文件内容", {
        "type": "object",
        "properties": {
            **_INTENT_PROP,
            "path": {"type": "string", "description": "文件路径"},
            "offset": {"type": "integer", "description": "可选:起始行号(1-based)。大文件被截断时,用 offset 分段读取中间部分"},
            "lines": {"type": "integer", "description": "可选:读取行数,与 offset 配合分段读取"},
        },
        "required": ["path", "intent"],
    }),
    ToolSchema("write_file", "写入或覆写文件", {
        "type": "object",
        "properties": {**_INTENT_PROP,
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "文件内容"},
        },
        "required": ["path", "content", "intent"],
    }),
    ToolSchema("delete_file", "删除文件", {
        "type": "object",
        "properties": {**_INTENT_PROP, "path": {"type": "string", "description": "文件路径"}},
        "required": ["path", "intent"],
    }),
    ToolSchema("list_dir", "列出目录下的文件", {
        "type": "object",
        "properties": {
            **_INTENT_PROP,
            "path": {"type": "string", "description": "目录路径"},
            "recursive": {"type": "boolean", "description": "可选:true 时一次列出整个目录树(相对路径),避免逐层多次探索;了解项目结构时建议用"},
        },
        "required": ["path", "intent"],
    }),
    ToolSchema("search_file", "在文件中搜索内容,返回匹配行+行号", {
        "type": "object",
        "properties": {
            **_INTENT_PROP,
            "path": {"type": "string", "description": "文件路径"},
            "pattern": {"type": "string", "description": "要搜索的内容(如 TODO、方法名、类名)"},
            "context": {"type": "integer", "description": "可选:匹配行上下各取几行上下文"},
        },
        "required": ["path", "pattern", "intent"],
    }),
    ToolSchema("run_shell", "执行 shell 命令", {
        "type": "object",
        "properties": {**_INTENT_PROP, "cmd": {"type": "string", "description": "要执行的命令"}},
        "required": ["cmd", "intent"],
    }),
    ToolSchema("run_tests", "运行测试,支持多语言", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "可选:只运行指定测试文件或目录(相对项目根,如 test_calc.py);省略则运行全部测试"},
            "test_command": {"type": "string", "description": "可选:测试命令。Python 用 pytest(默认);Java 用 mvn -B test(batch 模式禁进度条,输出干净);Node 用 npm test;Go 用 go test"},
            **_INTENT_PROP,
        },
        "required": ["intent"],
    }),
    ToolSchema("stop", "任务完成,停止。在 reason 中描述你的修改内容和结果。", {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "你做了什么修改、测试结果如何(用自然语言叙述,如'修改了 calc.py 将 add 函数返回值从 a+b 改为 a+b+1,add(2,2)=5 符合测试断言,1 个测试全部通过')"},
            **_INTENT_PROP,
        },
        "required": ["reason", "intent"],
    }),
]


# 对话历史条数上限:长会话下防止上下文无限膨胀(真实 LLM 上下文窗口有限),
# 超过则丢弃最早的条目,保留最新上下文。mock 客户端忽略 messages,不受影响。
MAX_HISTORY_MESSAGES = 30
# 完整工具回灌保留的最近轮数:更早轮次的完整 [结果] 压缩成一行摘要
# (Claude Code 式历史压缩——保留上下文要点,丢弃冗余全文)。
MAX_FULL_STEPS = 8


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        config: Config,
        memory,
        validator=Validator.parse,
        dispatcher=dispatch,
        guard=guardrail,
        on_event: Callable[[dict], None] | None = None,
        hitl_enabled: bool = False,
    ):
        self.llm = llm
        self.config = config
        self.memory = memory
        self.validator = validator
        self.dispatch = dispatcher
        self.guard = guard
        self.on_event = on_event or (lambda e: None)
        self.hitl_enabled = hitl_enabled
        # HITL 挂起/恢复机制(threading.Event)。approval_id 用自增计数器(确定性,
        # 不用 uuid/随机),保证同一脚本下审批序号可复现。
        self._approval_seq = 0
        self._pending_approval: dict | None = None   # {approval_id, action, verdict, decision}
        self._lock = threading.Lock()
        self._new_approval = threading.Event()    # 有 pending 审批出现时 set(供外部等待)
        self._decision_ready = threading.Event()  # approve() 调用后 set(唤醒挂起的循环)
        self.conversation_history: list[Message] = []  # 对话历史:每轮追加 assistant + tool 消息

    def _append_history(self, msg: Message) -> None:
        """追加一条对话历史:超 MAX_FULL_STEPS 轮后压缩最早轮次,超上限丢弃最早条目。"""
        self.conversation_history.append(msg)
        self._compact_old_steps()
        if len(self.conversation_history) > MAX_HISTORY_MESSAGES:
            del self.conversation_history[: len(self.conversation_history) - MAX_HISTORY_MESSAGES]

    def _compact_old_steps(self) -> None:
        """把最早的完整工具回灌压缩成一行摘要(确定性纯逻辑,可单测)。

        「[上一步] ActionName: intent\n[结果]\n…」这类消息超过 MAX_FULL_STEPS 条时,
        最老的压缩为「(历史) ActionName: intent」——保留"做了什么"的要点,
        丢弃全文结果(上下文聚焦最近轮次,避免膨胀导致回答冗余/失焦)。
        """
        step_idx = [i for i, m in enumerate(self.conversation_history)
                    if m.content.startswith("[上一步]")]
        excess = len(step_idx) - MAX_FULL_STEPS
        if excess <= 0:
            return
        for i in step_idx[:excess]:
            m = self.conversation_history[i]
            first_line = m.content.split("\n")[0]  # "[上一步] ActionName: intent"
            self.conversation_history[i] = Message("user", f"(历史) {first_line[4:]}")

    def _build_messages(self, task: str, state: LoopState) -> list[Message]:
        convs = self.memory.load_conventions()
        sys = Message("system", (
            "你是一个 coding agent,帮助用户处理代码任务。"
            "可用工具:read_file/write_file/delete_file/list_dir/search_file/run_shell/run_tests/stop。"
            "\n\n## 工作方式"
            "\n1. 每次只调用一个工具,附 intent(一句话动机)。"
            "\n2. 先理解需求再动手,只做用户要求的事。"
            "\n3. 任务完成:先简短总结,再调 stop(reason 写工作总结)。"
            f"\n4. 尽量在 {self.config.guardrails.max_rounds} 轮工具调用内完成(硬上限 {self.config.guardrails.hard_max_rounds} 轮)。"
            "请提前规划:一次读齐所需文件、避免重复跑相同测试、避免重复执行已成功的操作。"
            "\n\n## 意图分流"
            "\n- 「列出文件/有哪些文件」:调 list_dir(建议 recursive=true 一次列出整个目录树)→ 直接回复文件名列表 → stop。**不要读文件内容,不要逐层多次 list_dir,不要跑测试,不要用 shell。**"
            "\n- 「列出文件内容」:list_dir 了解结构 → 回复文件清单 + 每个文件 1-2 行概述。**不要读取所有文件的完整内容**(除非用户指名某个文件)。"
            "\n- 「列出/查看 xxx 文件的内容」:调 read_file 读该文件 → 回复内容或概述 → stop。**不要读其他文件。**大文件被截断时用 offset/lines 参数分段读取,不要重复整读;已读过的行区间不要重复读,用 offset 继续读未读部分。"
            "\n- **定位代码先 search_file**:一次找到所有匹配位置与行号,再只读相关行区间(offset/lines)。**不要逐段读全文拼凑**——那是低效且浪费轮数的方式。"
            "\n- 修复/改代码:读→改→跑测试→总结→stop;先看懂再改。"
            "\n- 只跑指定测试:run_tests 带 path 参数;Java 项目用 test_command=\"mvn -B test\"(batch 模式,输出干净无进度条,校验器解析更准)。"
            "\n- 分析/评估项目:读 1-3 个关键文件→给出分析→stop;不改代码,不跑测试(除非用户要求)。"
            "\n- 衔接词(继续/然后呢/为什么):基于上一步结果继续;上一步失败则修复重测,完成则总结。"
            "\n- 多任务(先…再…):逐个完成,全部完成后统一总结。"
            "\n\n## shell 命令不可用"
            "\n- shell 命令需要人工审批,当前模式通常不可执行。**不要尝试 grep/find/cat/ls 等 shell 命令查找文件**——用 read_file/list_dir 即可。被拦截后不要换命令反复尝试。"
            "\n\n## 严禁"
            "\n- 修改测试文件(测试断言是真理)。"
            "\n- 用户只要列文件/看文件,你却读内容或跑测试。"
            "\n- 无文字回复直接 stop。"
            "\n\n## 回复风格"
            "\n- 直接回答用户的问题,先结论后细节,简短精炼。"
            "\n- 不要复述用户任务,不要输出思考过程,不要逐条列举你调用的工具。"
            "\n- 测试结果一句话带过(如「测试通过:3 passed」);失败时指出失败项与原因。"
            "\n- **文件清单/概述等长内容只输出一次**:中途输出过就不再在 stop 总结里重复;"
            "\n- **使用 markdown 格式回复**:标题(##)、无序列表(-)、行内代码(`code`)、代码块(``` 围栏)、加粗(**重要**)。"
            + ("\n项目约定:\n" + "\n".join(convs) if convs else "")
        ))
        msgs = [sys]
        # 对话历史在前(时间顺序),新任务在最后——否则最新指令被夹在历史中间,
        # 真实 LLM 会按错误的时间顺序理解上下文(mock 客户端忽略 messages,不受影响)。
        msgs.extend(self.conversation_history)
        msgs.append(Message("user", task))
        if state.feedback_history:
            fb = state.feedback_history[-1]
            if fb.status == "FAIL":
                lines = [f"上一轮测试失败 {len(fb.failed_tests)} 项:"]
                for ft in fb.failed_tests:
                    lines.append(f"- {ft.nodeid} [{ft.category.value}] @ {ft.file}:{ft.line}")
                    if ft.assertion_diff:
                        lines.append(f"  断言 {ft.assertion_diff}")
                    lines.append(f"  建议:{strategy_hint(ft.category)}")
                # 用首个失败用例的类别检索历史修复;failed_tests 为空则跳过
                # (否则 `ft` 为 for 循环遗留变量,空列表时未绑定 → UnboundLocalError)。
                if fb.failed_tests:
                    hist = self.memory.retrieve(fb.failed_tests[0].category)
                    if hist:
                        lines.append("历史同类修复:")
                        for h in hist:
                            lines.append(f"  - {h.symptom} → {h.fix}")
                msgs.append(Message("user", "\n".join(lines)))  # user 角色兼容所有 API("tool" 需 tool_call_id 配对)
        for c in state.context_injected:
            msgs.append(Message("system", c))
        return msgs

    def _record_read_cache(self, action: ReadFile, tr: ToolResult) -> None:
        """记录一次真实读取的已读内容/行区间,累积到缓存。

        解析 read_file 输出中的行数信息:
        - 整读: `(共 N 行)\n...` 或含「已截断」→ 未截断标记 full
        - 分段: `已读第 X-Y 行(共 N 行)` → 累积 read_rows
        累积所有分段覆盖全部行 → full=True,之后重复读回灌完整拼接。
        """
        if not tr.ok:
            return
        out = tr.output or ""
        cache = self._read_cache.get(action.path)
        if cache is None:
            cache = {"text": "", "total": 0, "read_rows": set(), "full": False}
            self._read_cache[action.path] = cache
        import re
        m = re.search(r"共 (\d+) 行", out)
        if m:
            cache["total"] = int(m.group(1))
        if action.offset is None:
            # 整读:未截断 → 全文已读;截断 → 保留已读部分(头尾)
            if "已截断" not in out:
                cache["full"] = True
            cache["text"] = out
        else:
            m2 = re.search(r"已读第 (\d+)-(\d+) 行", out)
            if m2:
                lo, hi = int(m2.group(1)), int(m2.group(2))
                cache["read_rows"].update(range(lo - 1, hi))
            cache["text"] = cache["text"] + "\n" + out
            if cache["total"] and len(cache["read_rows"]) >= cache["total"]:
                cache["full"] = True

    def _execute_action(self, action, intent, state, ts_provider) -> tuple[ToolResult, Verdict, Feedback | None]:
        """执行单个动作:护栏判定 → 分发 → 校验。供主循环与批处理复用。"""
        v = self.guard(action, self.config)
        vname = type(v).__name__
        if vname == "Deny":
            tr = ToolResult(ok=False, output="", error=f"被护栏拒绝:{v.reason}。该命令被禁止,不要重复尝试,请改用其他方式。")
            fb = None
        elif vname == "NeedsApproval":
            if self.hitl_enabled:
                aid, decision, timed_out = self._suspend_for_approval(action, v, intent)
                if decision:
                    tr = self.dispatch(action, self.config)
                    fb = None
                    if isinstance(action, RunTests) and tr.structured is not None:
                        fb = self.validator(tr.structured, self.config.feedback.max_traceback_excerpt_lines)
                        tr = ToolResult(ok=fb.status == "PASS", output=tr.output, structured=tr.structured, error=None)
                else:
                    prefix = "审批超时" if timed_out else "被拒"
                    tr = ToolResult(ok=False, output="", error=f"{prefix}:{v.reason}")
                    fb = None
            else:
                tr = ToolResult(ok=False, output="", error=f"需人工审批:{v.reason}。该动作类型当前不可执行,不要重复尝试,请改用 read_file/list_dir/write_file 或直接文字回复。")
                fb = None
        else:
            tr = self.dispatch(action, self.config)
            fb = None
            if isinstance(action, RunTests) and tr.structured is not None:
                fb = self.validator(tr.structured, self.config.feedback.max_traceback_excerpt_lines)
                tr = ToolResult(ok=fb.status == "PASS", output=tr.output, structured=tr.structured, error=None)
        return tr, v, fb

    def _process_action(self, action, intent, state, steps, ts_provider) -> tuple[str | None, LoopState, Feedback | None]:
        """处理单个动作:重复读检测 → 护栏 → 执行 → 事件 → 历史 → 反馈 → 停机判断。

        返回 (停机原因或 None, 新 state, 本轮 fb)。主循环对批处理(多个动作)
        逐个调用本方法,直到某动作触发停机。
        """
        # 已读文件缓存:累积拼接 + 完整回灌。
        # 核心洞察:agent 反复读取是因为读不到完整内容(截断)又不敢在不完整
        # 信息下动手——正确做法是「满足需求」(已读内容累积,重复读时回灌完整
        # 拼接),而不是「拒绝需求」(提示别读了 / stuck 停机,任务就失败了)。
        if isinstance(action, ReadFile):
            cache = self._read_cache.get(action.path)
            if cache is not None and cache["full"]:
                # 已完整读取:回灌缓存全文(agent 真正看到),不真读
                self._cache_hits += 1
                hint = (f"文件 {action.path} 已完整读取(内容来自缓存,共 {cache['total']} 行)。"
                        "请基于完整内容继续下一步:写代码、跑测试,或调用 stop 总结。")
                if self._cache_hits >= 3:
                    hint += " 若仍缺信息,请用 search_file 定位具体内容,不要重复整读。"
                state.context_injected.append(hint)
                tr = ToolResult(ok=True, output=cache["text"])
                self.on_event({"type": "action", "action": "ReadFile", "intent": intent,
                               "verdict": "Allow", "ok": True, "feedback": None,
                               "error": None, "path": action.path, "from_cache": True})
                steps.append(Step(turn=AssistantTurn(action=action, intent=intent, raw=""),
                                  verdict=Allow(), tool_result=tr, feedback=None, ts=ts_provider()))
                self._append_history(Message(
                    "user",
                    f"[上一步] ReadFile: {intent}\n[结果]\n(已完整读取,内容来自缓存)\n{cache['text']}\n\n{hint}"
                ))
                return None, state, None
            # 首次读或未完整:标记需记录缓存(统一执行路径在后面,避免重复执行)
            self._need_cache_record = action
        # 连续被护栏拦截的动作计数:达到阈值后注入提示,防止在被拒操作上空转。
        v = self.guard(action, self.config)
        vname = type(v).__name__
        if vname in ("Deny", "NeedsApproval") and not (vname == "NeedsApproval" and self.hitl_enabled):
            self._rejected_streak = getattr(self, "_rejected_streak", 0) + 1
            if self._rejected_streak >= 3:
                state.context_injected.append(
                    "你已连续多次尝试被护栏拦截的动作。请停止尝试被拦截的操作,"
                    "改用可用工具(read_file/list_dir/write_file)或直接文字回复用户。")
        else:
            self._rejected_streak = 0
        # 执行:护栏 → 分发 → 校验
        tr, _, fb = self._execute_action(action, intent, state, ts_provider)
        # 首次读(非缓存命中):记录累积缓存
        if getattr(self, "_need_cache_record", None) is action:
            self._record_read_cache(action, tr)
            self._need_cache_record = None
        # 探索/修复动作(非 RunTests)重置 no_change_streak:agent 在推进
        # (读文件/写代码/找配置),测试连续失败不该算"无变化"——否则写完代码
        # 跑测试失败 2 次就被 stuck 误杀(真实历史:写完填空→测试失败→ListDir
        # 找 pom→再测试失败,agent 在修复却被终止)。
        if not isinstance(action, RunTests):
            state.no_change_streak = 0
        # 合并为单个 action 事件:动作名 + 护栏判定 + 结果 + 反馈 + 目标路径
        # (path 让前端/历史可见 agent 操作对象,否则 94 次 ReadFile 全显示
        # "ReadFile" 无法诊断在重复读哪个文件)
        action_name = type(action).__name__
        target = getattr(action, "path", None) or getattr(action, "cmd", None)
        self.on_event({"type": "action", "action": action_name, "intent": intent,
                       "verdict": vname, "ok": tr.ok, "feedback": _fb_to_dict(fb),
                       "error": tr.error, "path": target})
        steps.append(Step(turn=AssistantTurn(action=action, intent=intent, raw=""),
                          verdict=v, tool_result=tr, feedback=fb, ts=ts_provider()))
        # 历史回灌:精简结果 + 统一提示
        output_text = tr.output if tr.output else (tr.error or "(无输出)")
        if action_name == "RunTests":
            if fb is not None:
                output_text = f"测试结果: {fb.status} — {fb.summary}"
            else:
                output_text = _truncate_middle(output_text, head=200, tail=100, limit=400)
        else:
            output_text = _truncate_middle(output_text, head=500, tail=400, limit=900)
        next_hint = "请根据以上结果决定下一步:任务完成则调用 stop(reason 附简短总结),否则继续。"
        self._append_history(Message(
            "user",
            f"[上一步] {action_name}: {intent}\n[结果]\n{output_text}\n\n{next_hint}"
        ))
        # 最近一次工具结果摘要(stop trivial 兜底展示用);Stop 自身输出不算
        if not isinstance(action, Stop):
            self._last_tool_summary = output_text if output_text else None
        # 反馈 → 状态更新 + PASS 提示
        if fb:
            state = update_after_feedback(state, fb, self.config)
            if fb.status == "PASS":
                state.context_injected.append(
                    "测试全部通过!调用 stop,在 reason 字段里用自然语言说明你做了什么修改。"
                    "例如 reason:'修改了 calc.py,将 add 返回值从 a+b 改为 a+b+1,"
                    "使 add(2,2)=5 通过测试。'"
                )
        # 停机判断:Stop 动作 / decide_stop
        if isinstance(action, Stop):
            reason = action.reason or ""
            if reason and reason not in ("no_tool_call", "done"):
                if not _is_redundant(reason, self._emitted_texts):
                    self.on_event({"type": "response", "text": reason})
            elif not self._responded_this_round:
                self._any_response = True
                self.on_event({"type": "response", "text": self._last_tool_summary or "(任务完成)"})
            return "stopped", state, fb
        stop = decide_stop(state, self.config)
        if stop:
            if not self._any_response:
                note = {"max_rounds": "已达到最大执行轮数", "stuck": "连续失败无进展"}.get(stop, stop)
                self.on_event({"type": "response", "text": f"({note},停止执行)"})
            return stop, state, fb
        return None, state, fb

    def _suspend_for_approval(self, action, verdict, intent: str = "") -> tuple[str, bool, bool]:
        """登记一条 pending 审批并挂起循环,阻塞到 approve() 唤醒或超时。

        返回 (approval_id, decision, timed_out)。挂起前先发 pending_approval 事件(含
        approval_id/reason/intent),供 WebUI 渲染审批按钮(§A.6 ① 弹审批→人类决定链路)。
        挂起用 threading.Event,不取系统时间做判定,不依赖 LLM——人类决定经 approve()
        注入后才恢复,机制本身在给定 decision 下确定(§A.4 可单测)。唤醒后在同一把锁内
        原子取回 decision 并清空 pending,避免 run 线程与潜在的双击 approve 在锁外竞态。

        审批超时(approval_timeout_sec,来自 config.guardrails):等待超过阈值仍无人
        决定,按拒绝处理(timed_out=True),并发出 approval_timeout 事件供前端置灰按钮;
        已挂起的审批随即失效,之后 approve() 抛 KeyError。

        注意:hitl_enabled=True 时 run() 会阻塞在此,必须在独立线程调用 run()
        (否则主线程永久挂起);由 WebUI/CLI 的驱动方负责线程化。
        """
        with self._lock:
            self._approval_seq += 1
            aid = f"approval-{self._approval_seq}"
            self._pending_approval = {
                "approval_id": aid, "action": action, "verdict": verdict,
                "intent": intent, "decision": None,
            }
            self._new_approval.set()
            self._decision_ready.clear()
        # 挂起前发事件:把 approval_id + reason + intent 推给前端,人类据此决定。
        reason = getattr(verdict, "reason", "")
        self.on_event({"type": "pending_approval", "approval_id": aid,
                        "reason": reason, "intent": intent})
        # 阻塞:等待人类 approve,超时按拒绝处理(不执行危险动作)。
        timeout = self.config.guardrails.approval_timeout_sec
        got = self._decision_ready.wait(timeout=timeout)
        with self._lock:
            p = self._pending_approval
            decision = bool(p["decision"]) if p and got else False
            self._pending_approval = None
        if not got:
            self.on_event({"type": "approval_timeout", "approval_id": aid,
                           "timeout_sec": timeout, "reason": reason, "intent": intent})
        return aid, decision, not got

    def approve(self, approval_id: str, decision: bool) -> None:
        """人类对 pending 审批给出决定并唤醒挂起的循环。

        未知或已处理的 approval_id 抛 KeyError。决定为 True 则循环恢复后执行该动作,
        False 则回灌"被拒"。
        """
        with self._lock:
            p = self._pending_approval
            if p is None or p["approval_id"] != approval_id:
                raise KeyError(f"未知或已处理的审批: {approval_id}")
            p["decision"] = decision
        self._decision_ready.set()

    def wait_for_pending_approval(self, timeout: float = 5.0):
        """阻塞到有 pending 审批出现,返回其 approval_id;超时返回 None(测试用)。"""
        self._new_approval.wait(timeout=timeout)
        with self._lock:
            self._new_approval.clear()
            return self._pending_approval["approval_id"] if self._pending_approval else None

    def current_pending(self) -> dict | None:
        """非阻塞返回当前 pending 审批快照(供 WebUI/CLI 轮询);无则 None。不回显明文 key。"""
        with self._lock:
            if not self._pending_approval:
                return None
            p = self._pending_approval
            return {
                "approval_id": p["approval_id"],
                "reason": getattr(p["verdict"], "reason", ""),
                "intent": p.get("intent", ""),
            }

    def run(self, task: str, ts_provider: Callable[[], str], prior_history: list[Message] | None = None) -> RunResult:
        state = LoopState()
        steps: list[Step] = []
        outcome = "error"
        final_fb = None
        # 多轮对话:从先前对话恢复上下文,使 agent 能基于历史继续。
        if prior_history:
            self.conversation_history = list(prior_history)
        # 全程是否发过任何文字回复(停机兜底判断用);最近一次工具结果摘要
        # (stop 兜底时展示给用户,如「列出文件」直接看到列表)。
        self._any_response = False
        self._last_tool_summary = None
        # 本任务已输出的全部 response 文本(Stop reason 去重用——真实 LLM 常在
        # 中途输出清单/概述后,Stop 时又把同一份内容完整输出一遍,前端重复显示)。
        self._emitted_texts: list[str] = []
        self._llm_calls = 0  # LLM 调用计数(批处理减少往返的度量)
        # 已读文件缓存 {path: {text, total, read_rows, full}}:累积已读内容,
        # 重复读回灌完整拼接(满足 agent "看到完整内容"的需求,而非拒绝)。
        self._read_cache: dict[str, dict] = {}
        # 缓存命中计数必须任务开始时重置!否则跨任务累积(WebUI 续聊复用同一
        # loop 实例)会误触发 stuck 停机(真实"意外终止"根因)。
        self._cache_hits = 0
        self._need_cache_record = None
        while True:
            state.rounds += 1
            # 达到软上限(max_rounds):注入「尽快收尾」提示,不终止——复杂任务
            # 可继续执行,直到 hard_max_rounds 才强制停(安全阀)。
            if state.rounds == self.config.guardrails.max_rounds:
                state.context_injected.append(
                    f"你已执行 {state.rounds} 轮工具调用(软上限)。如果任务已完成,请调用 stop 总结;"
                    f"如果仍需继续,请高效执行(避免重复读取/重复测试),"
                    f"系统最多允许 {self.config.guardrails.hard_max_rounds} 轮。")
            # 本轮是否已有文字输出(Respond / 工具后的总结),Stop trivial 时据此决定兜底。
            self._responded_this_round = False
            msgs = self._build_messages(task, state)
            try:
                self._llm_calls += 1
                turn = self.llm.complete(msgs, _AGENT_TOOLS, state.snapshot())
            except RuntimeError:
                outcome = "error"
                steps.append(Step(turn=None, verdict=None, tool_result=None, feedback=None, ts=ts_provider()))
                break
            # 纯文本回复(非 tool call):发送给前端,记录对话历史。
            # 回复后给 LLM 一次机会调用 stop;如果连续两次纯文本回复(中间无工具调用),
            # 说明 LLM 只是在反复说话不停止,自动结束循环防止死循环。
            if isinstance(turn.action, Respond):
                self._responded_this_round = True
                self._any_response = True
                self._emitted_texts.append(turn.action.text)
                self.on_event({"type": "response", "text": turn.action.text})
                self._append_history(Message("assistant", turn.action.text[:2000]))
                steps.append(Step(turn=turn, verdict=None, tool_result=ToolResult(ok=True, output=turn.action.text), feedback=None, ts=ts_provider()))
                # 连续 Respond 计数:上次也是 Respond 则加 1,否则从 1 开始。
                _consecutive_responds = getattr(self, '_consecutive_responds', 0)
                _consecutive_responds += 1
                self._consecutive_responds = _consecutive_responds
                if _consecutive_responds >= 3:
                    # LLM 连续回复文字但不 stop:自动结束,以 stopped 作为结局。
                    # 阈值 3(非 2):允许"先说明发现、再补充细节"的分段回复,
                    # 仅在连续 3 次无动作时才认定是只说不停。
                    outcome = "stopped"
                    self.on_event({"type": "response", "text": "(agent 回复完毕,自动停止)"})
                    break
                if _consecutive_responds == 2:
                    # 第 2 段回复:提示可继续工具或 stop(不强制,避免误杀分段说明)
                    state.context_injected.append(
                        "你已经回复了两段文字。如果还有未完成的动作,请继续调用工具;如果回答完毕,请调用 stop。")
                else:
                    # 第 1 次回复:注入提示让 LLM 调用 stop
                    state.context_injected.append("你已经完成了文字回复。如果回答完毕,请调用 stop。")
                continue
            # 工具调用伴随文字说明(OpenAI 协议 content+tool_calls 并存):
            # 先展示给用户,再执行工具——否则"只有工具调用,没有回复"。
            if turn.text and turn.text.strip():
                self._responded_this_round = True
                self._any_response = True
                self._emitted_texts.append(turn.text)
                self.on_event({"type": "response", "text": turn.text[:2000]})
                self._append_history(Message("assistant", turn.text[:2000]))
            # 非 Respond 的工具调用:重置连续 Respond 计数。允许 Respond→Tool→Respond 模式。
            self._consecutive_responds = 0
            # 批处理:LLM 一次返回多个 tool_calls → 逐个执行(减少往返提高效率,
            # 一次 LLM 调用完成多个读文件等,而非 N 次串行往返)。
            actions = [(turn.action, turn.intent)] + (list(getattr(turn, "actions", None) or []))
            stop_reason = None
            for act, intent in actions:
                sr, state, fb = self._process_action(act, intent, state, steps, ts_provider)
                final_fb = fb or final_fb
                if sr:
                    stop_reason = sr
                    break
            if stop_reason:
                outcome = "stopped" if stop_reason == "stopped" else stop_reason
                break
            continue
        # 任务结束记录记忆(循环外写,不破坏确定性)。
        # 成功:记录修改内容与测试结果;失败:记录症状,尝试提取已做的修改。
        self._record_memory(state, steps, final_fb, outcome, ts_provider)
        return RunResult(outcome=outcome, steps=steps, final_feedback=final_fb)

    def _record_memory(self, state, steps, final_fb, outcome, ts_provider):
        """从步骤中提取修复内容并写入记忆。成功/失败都记,fix 字段填实际修改。"""
        if final_fb is None:
            return

        # 确定分类:优先用当前反馈的失败用例,其次查历史,再无则用 Unknown。
        cat = None
        if final_fb.failed_tests:
            cat = final_fb.failed_tests[0].category
        elif final_fb.status == "PASS":
            # 全部通过:从历史中找最近一次 FAIL 的 category(本轮修复的目标)。
            for fb in reversed(state.feedback_history):
                if fb.status == "FAIL" and fb.failed_tests:
                    cat = fb.failed_tests[0].category
                    break
            # 无历史失败但有实际修改:用 Unknown 兜底,确保成功修复也被记录。
            if cat is None:
                cat = FailureCategory.Unknown
        if cat is None:
            return  # 无法归类,跳过

        # 提取修改内容:1) 从 WriteFile 步骤取文件路径 + 意图;
        # 2) 从 Stop 步骤的 reason 取工作总结。
        fix_parts = []
        for s in steps:
            if s.turn and isinstance(s.turn.action, WriteFile):
                fix_parts.append(f"{s.turn.action.path}: {s.turn.intent}")
        stop_reason = ""
        for s in reversed(steps):
            if s.turn and isinstance(s.turn.action, Stop) and s.turn.action.reason:
                stop_reason = s.turn.action.reason
                break
        if stop_reason and stop_reason not in ("no_tool_call", "done"):
            fix_parts.append(f"总结: {stop_reason}")
        fix = "; ".join(fix_parts) if fix_parts else "(无具体修改记录)"

        symptom = final_fb.summary
        if final_fb.status == "PASS":
            symptom = f"修复成功: {final_fb.summary}"

        self.memory.record_fix(Fix(
            category=cat.value, symptom=symptom, fix=fix, timestamp=ts_provider(),
        ))


def _is_redundant(text: str, prior_texts: list[str]) -> bool:
    """判定文本与已输出内容重复(确定性纯函数,可单测)。

    真实 LLM 常在任务中途输出文件清单/概述后,Stop 时把同一份内容完整
    再输出一遍。判定规则:
    - 完全相同;
    - 一方完整包含另一方(短 >= 20 字);
    - 前 30 字相同(高度重叠的开头)。
    满足任一即视为重复——已输出的内容就是最终答复,不应再发。
    """
    t = text.strip()
    if not t:
        return True
    for p in prior_texts:
        p = p.strip()
        if not p:
            continue
        if t == p:
            return True
        short, long = (t, p) if len(t) < len(p) else (p, t)
        if len(short) >= 20 and short in long:
            return True
        if len(t) >= 30 and len(p) >= 30 and t[:30] == p[:30]:
            return True
    return False


def _truncate_middle(text: str, head: int = 800, tail: int = 700, limit: int = 1500) -> str:
    """超过 limit 时保留头 head + 尾 tail,中间以省略标记连接(确定性纯函数)。

    整段截尾会丢失文件末尾/错误堆栈的关键信息;头尾保留让 agent 同时看到
    开头与结尾,避免基于不完整信息决策。
    """
    if len(text) <= limit:
        return text
    return text[:head] + "\n…(中间截断)…\n" + text[-tail:]


def _fb_to_dict(fb):
    if fb is None:
        return None
    return {"status": fb.status, "failed": len(fb.failed_tests), "passed": fb.passed_count, "summary": fb.summary}
