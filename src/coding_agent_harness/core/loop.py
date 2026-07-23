"""Agent 主循环。自实现,不寄生框架。
组织上下文 → 调 LLM → 解析动作 → 护栏 → (审批)→ 分发 → 校验 → 回灌 → 停机。"""
from __future__ import annotations
import threading
from typing import Callable, Any
from coding_agent_harness.config import Config
from coding_agent_harness.models import (
    AssistantTurn, Action, RunTests, Stop, ToolResult, Feedback, Step, RunResult, Fix,
)
from coding_agent_harness.llm.base import LLMClient, Message
from coding_agent_harness.tools.dispatch import dispatch
from coding_agent_harness.feedback.validator import Validator
from coding_agent_harness.feedback.taxonomy import strategy_hint
from coding_agent_harness.guardrails.guardrail import guardrail
from coding_agent_harness.core.state import LoopState, update_after_feedback, decide_stop


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

    def _build_messages(self, task: str, state: LoopState) -> list[Message]:
        convs = self.memory.load_conventions()
        sys = Message("system", (
            "你是一个 coding agent。可用工具:read_file/write_file/delete_file/list_dir/run_shell/run_tests/stop。"
            "每次输出一个动作并附 intent(一句话说明动机)。"
            + ("\n项目约定:\n" + "\n".join(convs) if convs else "")
        ))
        msgs = [sys, Message("user", task)]
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
                msgs.append(Message("tool", "\n".join(lines)))
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
                "approval_id": aid, "action": action, "verdict": verdict, "decision": None,
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

    def run(self, task: str, ts_provider: Callable[[], str]) -> RunResult:
        state = LoopState()
        steps: list[Step] = []
        outcome = "error"
        final_fb = None
        while True:
            state.rounds += 1
            msgs = self._build_messages(task, state)
            try:
                turn = self.llm.complete(msgs, [], state.snapshot())
            except RuntimeError:
                outcome = "error"
                steps.append(Step(turn=None, verdict=None, tool_result=None, feedback=None, ts=ts_provider()))
                break
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
            if fb:
                state = update_after_feedback(state, fb, self.config)
            final_fb = fb or final_fb
            if isinstance(turn.action, Stop):
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
