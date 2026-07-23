from coding_agent_harness.config import load_config
from coding_agent_harness.models import ReadFile, WriteFile, Stop
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
