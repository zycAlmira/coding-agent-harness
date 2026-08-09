"""循环状态与停机判断。确定性纯函数,可单测——反馈闭环(主贡献)的停机/策略逻辑。"""
from __future__ import annotations
from dataclasses import dataclass, field
from coding_agent_harness.config import Config
from coding_agent_harness.models import Feedback
from coding_agent_harness.feedback.taxonomy import FailureCategory


@dataclass
class LoopState:
    """agent 主循环的可变状态快照。

    计数字段均由 update_after_feedback 确定性维护,不依赖系统时间,
    在 mock LLM 下可单测复现。
    """
    rounds: int = 0
    last_category: FailureCategory | None = None
    same_category_streak: int = 0           # 连续同类失败计数(含当前轮)
    no_change_streak: int = 0              # 连续同一失败集合计数(含当前轮)
    last_feedback_status: str | None = None
    feedback_history: list[Feedback] = field(default_factory=list)
    steps: list = field(default_factory=list)
    context_injected: list[str] = field(default_factory=list)

    def snapshot(self) -> "LoopState":
        """返回一份浅拷贝快照(仅标量与列表引用),供回放/调试。"""
        s = LoopState()
        s.rounds = self.rounds
        s.last_category = self.last_category
        s.same_category_streak = self.same_category_streak
        s.no_change_streak = self.no_change_streak
        s.last_feedback_status = self.last_feedback_status
        return s


def _failed_set(fb: Feedback) -> frozenset:
    """提取一次反馈的失败用例 nodeid 集合,用于无变化判定。"""
    return frozenset(ft.nodeid for ft in fb.failed_tests)


def update_after_feedback(state: LoopState, fb: Feedback, config: Config) -> LoopState:
    """据 Feedback 更新循环状态:连续同类计数、无变化计数、策略提示。

    纯函数:不修改入参 state,返回新的 LoopState。确定性:相同输入恒同输出。
    """
    gr = config.guardrails
    cat = fb.failed_tests[0].category if fb.failed_tests else None

    # --- same_category_streak:连续同类失败计数(含当前轮) ---
    if cat is not None and cat == state.last_category:
        new_same = state.same_category_streak + 1
    elif cat is not None:
        new_same = 1          # 换了类别,但仍是失败,记为该类别的第 1 次
    else:
        new_same = 0          # 无失败用例(PASS 等),不计同类 streak

    # --- no_change_streak:连续同一失败集合计数(含当前轮) ---
    # 语义对齐测试契约:FAIL 时,首次失败记 1;与上一轮同集合则 +1;集合变了记 1;PASS 记 0。
    if fb.status != "FAIL":
        new_no_change = 0
    elif not state.feedback_history:
        new_no_change = 1                          # 首次失败:该失败集合的第 1 次
    else:
        prev = state.feedback_history[-1]
        if _failed_set(prev) == _failed_set(fb):
            new_no_change = state.no_change_streak + 1   # 与上一轮同一失败集合
        else:
            new_no_change = 1                      # 失败集合变了:新集合的第 1 次

    new = LoopState(
        rounds=state.rounds,
        last_category=cat,
        same_category_streak=new_same,
        no_change_streak=new_no_change,
        last_feedback_status=fb.status,
        feedback_history=state.feedback_history + [fb],
        steps=state.steps,
        context_injected=list(state.context_injected),
    )

    # --- 策略提示:回灌给 agent 的上下文线索 ---
    if new.same_category_streak >= gr.same_category_prompt_at:
        new.context_injected.append("连续同类失败,考虑换一种修复方向(换思路)")
    if new.no_change_streak >= gr.no_change_stop_at:
        new.context_injected.append("陷入死循环,请回退最近改动")
    return new


def decide_stop(state: LoopState, config: Config) -> str | None:
    """停机判断:返回停机原因字符串,或 None 表示继续。

    判定优先级:成功 > 硬回合上限 > 同类停机 > 无变化停机。确定性纯函数。
    max_rounds 是软上限(仅注入提示,见 loop),hard_max_rounds 才是强制终止的安全阀。
    """
    gr = config.guardrails
    # PASS 不再自动判"success"——留给 agent 一轮机会总结工作文字描述再 stop。
    # hard_max_rounds 兜底防止无限循环(正常任务由模型 stop / stuck 提前结束)。
    if state.rounds >= gr.hard_max_rounds:
        return "max_rounds"
    if state.same_category_streak >= gr.same_category_stop_at:
        return "stuck"
    if state.no_change_streak >= gr.no_change_stop_at:
        return "stuck"
    return None
