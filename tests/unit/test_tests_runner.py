from pathlib import Path
from coding_agent_harness.config import load_config
from coding_agent_harness.tools.tests_runner import run_tests

# tests/unit/test_tests_runner.py → parent=tests/unit → parent=tests → parent=repo 根
FIX = Path(__file__).parent.parent.parent / "fixtures" / "sample_pkg"


def _cfg(root: Path):
    import yaml
    import tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({"project_root": str(root), "llm": {"base_url": "x", "model": "m"}}, f)
    f.close()
    return load_config(f.name)


def test_run_tests_returns_pytest_run():
    r = run_tests(_cfg(FIX))
    assert r.exit_code != 0
    assert "test_add" in r.stdout
    assert "1 failed" in r.stdout
    assert r.duration_s >= 0


def test_run_tests_does_not_judge():
    # 只返回结构化结果,不返回 PASS/FAIL 布尔
    r = run_tests(_cfg(FIX))
    assert not hasattr(r, "status")
