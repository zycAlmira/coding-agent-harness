"""Agent 主循环。自实现,不寄生框架。
组织上下文 → 调 LLM → 解析动作 → 护栏 → (审批)→ 分发 → 校验 → 回灌 → 停机。"""
from __future__ import annotations
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
    ):
        self.llm = llm
        self.config = config
        self.memory = memory
        self.validator = validator
        self.dispatch = dispatcher
        self.guard = guard
        self.on_event = on_event or (lambda e: None)
        self._pending_approvals: dict[str, dict] = {}

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
                # HITL 完整挂起/恢复在 Task 15b 实现;此处简化为回灌"需审批"
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
