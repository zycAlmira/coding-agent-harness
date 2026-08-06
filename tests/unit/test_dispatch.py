from coding_agent_harness.config import load_config
from coding_agent_harness.models import ReadFile, WriteFile, Stop, RunTests
from coding_agent_harness.tools.dispatch import dispatch
import yaml
import tempfile


def _cfg(root):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({"project_root": str(root), "llm": {"base_url": "x", "model": "m"}}, f)
    f.close()
    return load_config(f.name)


def test_dispatch_write_then_read(tmp_path):
    cfg = _cfg(tmp_path)
    dispatch(WriteFile("a.txt", "hi"), cfg)
    r = dispatch(ReadFile("a.txt"), cfg)
    assert r.ok and r.output == "hi"


def test_dispatch_stop_returns_ok():
    cfg = _cfg(".")
    r = dispatch(Stop("done"), cfg)
    assert r.ok and "stop" in r.output.lower()


def test_dispatch_run_tests_with_path(tmp_path):
    import shutil
    from pathlib import Path
    FIX = Path(__file__).parent.parent.parent / "fixtures" / "sample_pkg"
    shutil.copytree(FIX, tmp_path / "ws", dirs_exist_ok=True)
    cfg = _cfg(tmp_path / "ws")
    r = dispatch(RunTests(path="test_calc.py"), cfg)
    assert "1 failed" in r.output
    assert r.structured is not None


def test_dispatch_run_tests_escape_returns_error(tmp_path):
    cfg = _cfg(tmp_path)
    r = dispatch(RunTests(path="../escape.py"), cfg)
    assert not r.ok
    assert "越界" in (r.error or "")
