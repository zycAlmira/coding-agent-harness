"""Agent 主循环。自实现,不寄生框架。
组织上下文 → 调 LLM → 解析动作 → 护栏 → (审批)→ 分发 → 校验 → 回灌 → 停机。"""
from __future__ import annotations
import threading
from typing import Callable
from coding_agent_harness.config import Config
from coding_agent_harness.models import (
    RunTests, Stop, ToolResult, Step, RunResult, Fix, Respond,
)
from coding_agent_harness.llm.base import LLMClient, Message, ToolSchema
from coding_agent_harness.tools.dispatch import dispatch
from coding_agent_harness.feedback.validator import Validator
from coding_agent_harness.feedback.taxonomy import strategy_hint
from coding_agent_harness.guardrails.guardrail import guardrail
from coding_agent_harness.core.state import LoopState, update_after_feedback, decide_stop


# Agent 可用工具清单(JSON Schema),供真实 LLM 的 function-calling 使用。
# 参数名与 openai_compat._ACTION_BUILDERS 的 key 对齐。
_INTENT_PROP = {"intent": {"type": "string", "description": "执行此动作的理由(一句话)"}}

_AGENT_TOOLS = [
    ToolSchema("read_file", "读取文件内容", {
        "type": "object",
        "properties": {**_INTENT_PROP, "path": {"type": "string", "description": "文件路径"}},
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
        "properties": {**_INTENT_PROP, "path": {"type": "string", "description": "目录路径"}},
        "required": ["path", "intent"],
    }),
    ToolSchema("run_shell", "执行 shell 命令", {
        "type": "object",
        "properties": {**_INTENT_PROP, "cmd": {"type": "string", "description": "要执行的命令"}},
        "required": ["cmd", "intent"],
    }),
    ToolSchema("run_tests", "运行测试(pytest)", {
        "type": "object", "properties": _INTENT_PROP, "required": ["intent"],
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

    def _build_messages(self, task: str, state: LoopState) -> list[Message]:
        convs = self.memory.load_conventions()
        sys = Message("system", (
            "你是一个 coding agent。可用工具:read_file/write_file/delete_file/list_dir/run_shell/run_tests/stop。"
            "每次输出一个工具调用并附 intent(一句话说明动机)。"
            "\n重要规则:"
            "\n- 修复实现代码(src),不要修改测试文件。测试断言是真理,实现代码必须迁就测试。"
            "\n- 先读代码理解问题,再动手修改,最后跑测试验证。"
            "\n- 测试通过后,先输出一段文字总结(不调用任何工具),再调用 stop。"
            "\n  例如:测试全部通过。修改内容:把 add 的返回值从 a+b 改为 a+b+1,使得 add(2,2)=5 符合测试断言。"
            "\n- 可以随时用文字回答问题或说明当前进展(不调用工具即可)。"
            + ("\n项目约定:\n" + "\n".join(convs) if convs else "")
        ))
        msgs = [sys, Message("user", task)]
        # 追加对话历史(之前各轮的 assistant 动作 + tool 结果),
        # 让真实 LLM 拥有完整上下文记忆(mock 客户端忽略 messages,不受影响)。
        msgs.extend(self.conversation_history)
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

    def _suspend_for_approval(self, action, verdict, intent: str = "") -> tuple[str, bool]:
        """登记一条 pending 审批并挂起循环,阻塞到 approve() 唤醒。

        返回 (approval_id, decision)。挂起前先发 pending_approval 事件(含
        approval_id/reason/intent),供 WebUI 渲染审批按钮(§A.6 ① 弹审批→人类决定链路)。
        挂起用 threading.Event,不取系统时间做判定,不依赖 LLM——人类决定经 approve()
        注入后才恢复,机制本身在给定 decision 下确定(§A.4 可单测)。唤醒后在同一把锁内
        原子取回 decision 并清空 pending,避免 run 线程与潜在的双击 approve 在锁外竞态。

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
        # 阻塞:等待人类 approve。无超时——挂起即等待人类决策。
        self._decision_ready.wait()
        with self._lock:
            p = self._pending_approval
            decision = bool(p["decision"]) if p else False
            self._pending_approval = None
        return aid, decision

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

    def run(self, task: str, ts_provider: Callable[[], str]) -> RunResult:
        state = LoopState()
        steps: list[Step] = []
        outcome = "error"
        final_fb = None
        while True:
            state.rounds += 1
            msgs = self._build_messages(task, state)
            try:
                turn = self.llm.complete(msgs, _AGENT_TOOLS, state.snapshot())
            except RuntimeError:
                outcome = "error"
                steps.append(Step(turn=None, verdict=None, tool_result=None, feedback=None, ts=ts_provider()))
                break
            # 纯文本回复(非 tool call):发送给前端,记录对话历史,继续循环。
            # LLM 可在回复后调用工具或 stop,实现"回答+操作"穿插。
            if isinstance(turn.action, Respond):
                self.on_event({"type": "response", "text": turn.action.text})
                self.conversation_history.append(Message("assistant", turn.action.text[:2000]))
                steps.append(Step(turn=turn, verdict=None, tool_result=ToolResult(ok=True, output=turn.action.text), feedback=None, ts=ts_provider()))
                continue
            v = self.guard(turn.action, self.config)
            self.on_event({"type": "guardrail_verdict", "verdict": type(v).__name__, "intent": turn.intent})
            vname = type(v).__name__
            if vname == "Deny":
                tr = ToolResult(ok=False, output="", error=f"被护栏拒绝:{v.reason}")
                fb = None
            elif vname == "NeedsApproval":
                if self.hitl_enabled:
                    # HITL 完整化:挂起循环等人类审批,据决定执行或回灌"被拒"
                    aid, decision = self._suspend_for_approval(turn.action, v, turn.intent)
                    if decision:
                        tr = self.dispatch(turn.action, self.config)
                        fb = None
                        if isinstance(turn.action, RunTests) and tr.structured is not None:
                            fb = self.validator(tr.structured, self.config.feedback.max_traceback_excerpt_lines)
                            tr = ToolResult(ok=fb.status == "PASS", output=tr.output, structured=tr.structured, error=None)
                    else:
                        tr = ToolResult(ok=False, output="", error=f"被拒:{v.reason}")
                        fb = None
                else:
                    # 非 HITL:回灌"需审批"字符串,不挂起(保持 Task 15 行为)
                    tr = ToolResult(ok=False, output="", error=f"需人工审批:{v.reason}")
                    fb = None
            else:
                tr = self.dispatch(turn.action, self.config)
                fb = None
                if isinstance(turn.action, RunTests) and tr.structured is not None:
                    fb = self.validator(tr.structured, self.config.feedback.max_traceback_excerpt_lines)
                    tr = ToolResult(ok=fb.status == "PASS", output=tr.output, structured=tr.structured, error=None)
            self.on_event({"type": "tool_result", "ok": tr.ok, "feedback": _fb_to_dict(fb)})
            steps.append(Step(turn=turn, verdict=v, tool_result=tr, feedback=fb, ts=ts_provider()))
            # 记录本轮对话历史(下轮 _build_messages 时追加到消息列表),
            # 让真实 LLM 能基于之前的执行结果做下一步决策。
            # 用 "user" 角色(而非 assistant+tool)回灌,避免与 OpenAI
            # function-calling 协议的 assistant/tool 角色语义冲突——
            # 我们的 Message 抽象只有 role+content,无法表达
            # tool_calls/tool_call_id 结构;用 user 消息告知"上一步做了什么、
            # 结果是什么",让模型清楚知道需要继续输出下一个 function call。
            action_name = type(turn.action).__name__
            output_text = tr.output if tr.output else (tr.error or "(无输出)")
            self.conversation_history.append(Message(
                "user",
                f"[上一步] {action_name}: {turn.intent}\n"
                f"[结果]\n{output_text[:1500]}\n\n"
                f"请基于以上结果,输出下一个工具调用继续完成任务。"
                f"如果任务已完成,调用 stop。"
            ))
            if fb:
                state = update_after_feedback(state, fb, self.config)
                # 测试通过后不自动停机,注入提示引导 agent 总结工作再 stop。
                if fb.status == "PASS":
                    state.context_injected.append(
                        "测试全部通过!调用 stop,在 reason 字段里用自然语言说明你做了什么修改。"
                        "例如 reason:'修改了 calc.py,将 add 返回值从 a+b 改为 a+b+1,"
                        "使 add(2,2)=5 通过测试。'"
                    )
            final_fb = fb or final_fb
            if isinstance(turn.action, Stop):
                # Stop.reason 承载了 agent 的工作总结,发送给前端显示。
                if turn.action.reason and turn.action.reason not in ("no_tool_call", "done", ""):
                    self.on_event({"type": "response", "text": turn.action.reason})
                outcome = "stopped"
                break
            stop = decide_stop(state, self.config)
            if stop:
                outcome = stop
                break
        # 任务结束记录记忆(循环外写,不破坏确定性)
        if final_fb and final_fb.status == "FAIL" and final_fb.failed_tests:
            cat = final_fb.failed_tests[0].category
            self.memory.record_fix(Fix(category=cat.value, symptom=final_fb.summary, fix="(未修复)", timestamp=ts_provider()))
        return RunResult(outcome=outcome, steps=steps, final_feedback=final_fb)


def _fb_to_dict(fb):
    if fb is None:
        return None
    return {"status": fb.status, "failed": len(fb.failed_tests), "passed": fb.passed_count, "summary": fb.summary}
