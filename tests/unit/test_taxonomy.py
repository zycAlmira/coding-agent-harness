from coding_agent_harness.feedback.taxonomy import FailureCategory, strategy_hint


def test_all_categories_have_hint():
    for c in FailureCategory:
        assert isinstance(strategy_hint(c), str) and strategy_hint(c)


def test_hint_is_deterministic():
    assert strategy_hint(FailureCategory.AssertionFailure) == strategy_hint(FailureCategory.AssertionFailure)


def test_unknown_has_fallback():
    assert strategy_hint(FailureCategory.Unknown)
