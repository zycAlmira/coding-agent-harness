from pathlib import Path
from coding_agent_harness.feedback.validator import Validator
from coding_agent_harness.feedback.taxonomy import FailureCategory
from coding_agent_harness.models import PytestRun

FIX = Path(__file__).parent / "fixtures"


def _run(name: str) -> PytestRun:
    return PytestRun(exit_code=1, stdout=(FIX / name).read_text(), stderr="", duration_s=0.05)


def test_pass_when_no_failures():
    r = PytestRun(exit_code=0, stdout=(FIX / "pass.txt").read_text(), stderr="", duration_s=0.05)
    fb = Validator.parse(r)
    assert fb.status == "PASS"
    assert fb.failed_tests == []
    assert fb.passed_count == 2


def test_assertion_failure_classified():
    fb = Validator.parse(_run("assertion_fail.txt"))
    assert fb.status == "FAIL"
    assert len(fb.failed_tests) == 1
    ft = fb.failed_tests[0]
    assert ft.nodeid == "tests/test_calc.py::test_add"
    assert ft.category is FailureCategory.AssertionFailure
    assert ft.file == "tests/test_calc.py"
    assert ft.line == 5
    assert ft.assertion_diff == "assert 4 == 5"


def test_import_error_classified():
    fb = Validator.parse(_run("import_error.txt"))
    assert fb.status == "FAIL"
    cat = fb.failed_tests[0].category
    assert cat in (FailureCategory.ImportError, FailureCategory.CollectionError)


def test_summary_extracted():
    fb = Validator.parse(_run("assertion_fail.txt"))
    assert "1 failed" in fb.summary and "1 passed" in fb.summary


def test_traceback_excerpt_truncated_to_config(tmp_path):
    # 超长 traceback 应截断(此例短,仅断言非空)
    fb = Validator.parse(_run("assertion_fail.txt"))
    assert fb.failed_tests[0].traceback_excerpt


def test_parse_real_tb_short_format():
    """真实 `pytest --tb=short` 输出:位置行 `file:line: in test_name` 在 assert 行之前,
    且无 err 词。验证延迟 flush 能正确解析该顺序(_TB_LOC_SHORT 分支)。"""
    fb = Validator.parse(_run("tb_short.txt"))
    assert fb.status == "FAIL"
    assert len(fb.failed_tests) == 1
    ft = fb.failed_tests[0]
    assert ft.nodeid == "tests/sample_pkg/test_calc.py::test_add"
    assert ft.category is FailureCategory.AssertionFailure
    assert ft.file == "tests/sample_pkg/test_calc.py"
    assert ft.line == 5
    assert ft.assertion_diff == "assert 6 == 5"
    assert "assert 6 == 5" in ft.traceback_excerpt


def test_assertion_diff_from_e_line_fallback():
    """FAILED 行不带 `- assert...` 后缀时,_ASSERT_LINE 兜底从 `E assert` 行抽 diff。"""
    fb = Validator.parse(_run("assert_no_diff.txt"))
    assert fb.status == "FAIL"
    assert len(fb.failed_tests) == 1
    ft = fb.failed_tests[0]
    assert ft.nodeid == "tests/test_z.py::test_z"
    assert ft.file == "tests/test_z.py"
    assert ft.line == 9
    assert ft.category is FailureCategory.AssertionFailure
    # 兜底分支应抽到非空 diff,且为 `assert 7 == 42`
    assert ft.assertion_diff is not None
    assert "assert" in ft.assertion_diff
    assert ft.assertion_diff == "assert 7 == 42"
