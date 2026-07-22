from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.models import WriteFile, RunTests, Stop, AssistantTurn
from coding_agent_harness.feedback.taxonomy import FailureCategory


def _state(rounds=1, last_category=None, last_status=None):
    class S:
        pass
    s = S()
    s.rounds = rounds
    s.last_category = last_category
    s.last_feedback_status = last_status
    return s


def test_round_branch():
    mock = MockLLMClient([
        {"when": "round 1", "action": WriteFile("a.py", "x"), "intent": "写"},
        {"when": "always", "action": Stop("done"), "intent": "完成"},
    ])
    t = mock.complete([], [], _state(rounds=1))
    assert isinstance(t.action, WriteFile) and t.intent == "写"


def test_feedback_branch_changes_action():
    mock = MockLLMClient([
        {"when": "feedback.category == AssertionFailure", "action": WriteFile("a.py", "good"), "intent": "上次断言失败,改 off-by-one"},
        {"when": "always", "action": Stop("x"), "intent": "fallback"},
    ])
    t = mock.complete([], [], _state(last_category=FailureCategory.AssertionFailure))
    assert t.intent == "上次断言失败,改 off-by-one"
    assert t.action.content == "good"


def test_pass_branch():
    mock = MockLLMClient([
        {"when": "feedback.status == PASS", "action": Stop("done"), "intent": "全绿"},
        {"when": "always", "action": Stop("nope"), "intent": "x"},
    ])
    t = mock.complete([], [], _state(last_status="PASS"))
    assert t.intent == "全绿"


def test_no_match_raises():
    mock = MockLLMClient([{"when": "round 99", "action": Stop("x"), "intent": "x"}])
    try:
        mock.complete([], [], _state(rounds=1))
        assert False, "应抛错"
    except RuntimeError:
        pass
