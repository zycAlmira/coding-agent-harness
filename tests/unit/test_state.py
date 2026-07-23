from coding_agent_harness.core.state import LoopState, update_after_feedback, decide_stop
from coding_agent_harness.models import Feedback, FailedTest
from coding_agent_harness.feedback.taxonomy import FailureCategory
from coding_agent_harness.config import load_config
import yaml
import tempfile


def _cfg(**overrides):
    raw = {"project_root": ".", "llm": {"base_url": "x", "model": "m"},
           "guardrails": {"max_rounds": 8, "same_category_prompt_at": 2,
                           "same_category_stop_at": 3, "no_change_stop_at": 2}}
    raw["guardrails"].update(overrides)
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump(raw, f)
    f.close()
    return load_config(f.name)


def _fb(cat=FailureCategory.AssertionFailure, status="FAIL", nodeids=("a",)):
    return Feedback(status=status, failed_tests=[
        FailedTest(nodeid=n, category=cat, file="f", line=1, traceback_excerpt="", assertion_diff=None)
        for n in nodeids
    ], passed_count=0, summary="1 failed")


def test_streak_increments_same_category():
    cfg = _cfg()
    s = LoopState()
    s = update_after_feedback(s, _fb(FailureCategory.AssertionFailure), cfg)
    assert s.same_category_streak == 1
    s = update_after_feedback(s, _fb(FailureCategory.AssertionFailure), cfg)
    assert s.same_category_streak == 2


def test_streak_resets_on_category_change():
    cfg = _cfg()
    s = update_after_feedback(LoopState(), _fb(FailureCategory.AssertionFailure), cfg)
    s = update_after_feedback(s, _fb(FailureCategory.ImportError), cfg)
    assert s.same_category_streak == 1


def test_no_change_streak_when_same_failed_set():
    cfg = _cfg()
    s = update_after_feedback(LoopState(), _fb(nodeids=("a",)), cfg)
    s = update_after_feedback(s, _fb(nodeids=("a",)), cfg)
    assert s.no_change_streak == 2
    assert decide_stop(s, cfg) == "stuck"


def test_stop_on_max_rounds():
    cfg = _cfg(max_rounds=2)
    s = LoopState(rounds=2)
    assert decide_stop(s, cfg) == "max_rounds"


def test_stop_on_success():
    cfg = _cfg()
    s = LoopState(last_feedback_status="PASS")
    assert decide_stop(s, cfg) == "success"


def test_no_stop_midway():
    cfg = _cfg()
    s = update_after_feedback(LoopState(), _fb(), cfg)
    assert decide_stop(s, cfg) is None


def test_should_prompt_switch():
    cfg = _cfg()
    s = update_after_feedback(LoopState(), _fb(), cfg)
    s = update_after_feedback(s, _fb(), cfg)
    assert s.same_category_streak == 2  # 达 prompt_at
