"""Task 2: 值类型与数据模型 models.py 的单元测试。"""
from coding_agent_harness.models import (
    Action, Allow, Deny, NeedsApproval, AssistantTurn, WriteFile,
)


def test_action_is_union_of_variants():
    # WriteFile 应该被识别为 Action 联合类型的一员
    a = WriteFile(path="src/x.py", content="print(1)")
    assert isinstance(a, Action)


def test_verdicts_carry_reason():
    # Deny / NeedsApproval / Allow 三种判定各自携带原因或标志
    assert Deny(reason="rm -rf").reason == "rm -rf"
    assert NeedsApproval(reason="del").is_approval
    assert Allow().is_approval is False


def test_assistant_turn_has_intent():
    # AssistantTurn 记录 LLM 一次产出的动作、意图、原始文本
    t = AssistantTurn(action=WriteFile("a", "b"), intent="修 bug", raw="...")
    assert t.intent == "修 bug"
