"""脚本化 mock LLM。据当前 LoopState 选分支,确定性,不触网。"""
from __future__ import annotations
from coding_agent_harness.llm.base import LLMClient, Message, ToolSchema
from coding_agent_harness.models import AssistantTurn, Action


class MockLLMClient:
    """不触网的脚本化 LLM。

    构造时注入一段脚本(有序条件-动作条目列表),`complete` 据当前
    LoopState 选取**第一个匹配**的条目返回 AssistantTurn。选取逻辑
    纯确定性,故 §A.6 演示(治理拦截/反馈闭环/重点维度)可在无网络、
    无真实 LLM 下复现。
    """

    def __init__(self, script: list[dict]):
        # 条目形如 {"when": ..., "action": Action, "intent": str}
        self.script = script

    def complete(self, messages, tools, state) -> AssistantTurn:
        # 顺序遍历脚本,返回第一个 when 与当前 state 匹配的条目。
        for entry in self.script:
            if _matches(entry["when"], state):
                return AssistantTurn(
                    action=entry["action"],
                    intent=entry["intent"],
                    raw=f"mock:{entry['when']}",
                )
        # 无任何分支命中:视为脚本配置错误,抛 RuntimeError 而非静默兜底,
        # 保证测试与演示能捕获此错误路径。
        raise RuntimeError(
            f"mock 无匹配分支: rounds={getattr(state, 'rounds', None)} "
            f"last_category={getattr(state, 'last_category', None)}"
        )


def _matches(when: str, state) -> bool:
    """判断单个 when 条件是否命中当前 state。支持四种分支。"""
    # 1) always:无条件命中,通常作为脚本末尾兜底。
    if when == "always":
        return True
    # 2) round N:当前轮次等于指定整数。
    if when.startswith("round "):
        return getattr(state, "rounds", None) == int(when.split()[1])
    # 3) feedback.category == X:上一轮反馈的失败分类(枚举)值等于 X。
    if when.startswith("feedback.category == "):
        cat = getattr(state, "last_category", None)
        return cat is not None and cat.value == when.split("== ", 1)[1].strip()
    # 4) feedback.status == PASS:上一轮反馈状态字符串等于给定值。
    if when.startswith("feedback.status == "):
        return getattr(state, "last_feedback_status", None) == when.split("== ", 1)[1].strip()
    # 未知 when 形式:不命中,避免误兜底。
    return False
