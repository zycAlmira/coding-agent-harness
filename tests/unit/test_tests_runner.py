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


def test_run_tests_specific_path():
    # path 生效:只跑指定文件,输出含该文件的用例
    r = run_tests(_cfg(FIX), "test_calc.py")
    assert "test_add" in r.stdout
    assert "1 failed" in r.stdout


def test_run_tests_specific_path_isolates():
    # 不存在的路径直接报错且无任何用例运行:证明 path 真的传给了 pytest
    # (否则会照跑全套夹具,exit_code 仍为 1 且 stdout 有 test_add)
    r = run_tests(_cfg(FIX), "does_not_exist.py")
    assert r.exit_code != 0
    assert "no tests ran" in r.stdout
    assert "test_add" not in r.stdout


def test_run_tests_path_escape_rejected():
    # 测试路径不得逃出 project_root(安全边界,同文件工具路径围栏)
    import pytest as pt
    with pt.raises(ValueError):
        run_tests(_cfg(FIX), "../outside.py")
