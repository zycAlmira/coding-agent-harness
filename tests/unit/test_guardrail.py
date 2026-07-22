from coding_agent_harness.config import load_config
from coding_agent_harness.models import (
    WriteFile, DeleteFile, RunShell, ReadFile, RunTests, ListDir, Stop,
    Allow, Deny, NeedsApproval,
)
from coding_agent_harness.guardrails.guardrail import guardrail
import yaml, tempfile


def _cfg(blacklist=None, whitelist=None, root="."):
    raw = {
        "project_root": root,
        "llm": {"base_url": "x", "model": "m"},
        "guardrails": {
            "shell_blacklist": blacklist or ["rm -rf"],
            "shell_whitelist": whitelist or ["pytest"],
        },
    }
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump(raw, f); f.close()
    return load_config(f.name)


def test_delete_needs_approval():
    assert isinstance(guardrail(DeleteFile("a.py"), _cfg()), NeedsApproval)


def test_write_inside_project_allowed(tmp_path):
    cfg = _cfg(root=str(tmp_path))
    assert isinstance(guardrail(WriteFile("src/a.py", "x"), cfg), Allow)


def test_write_outside_project_needs_approval(tmp_path):
    cfg = _cfg(root=str(tmp_path))
    # 用 ../ 逃逸
    assert isinstance(guardrail(WriteFile("../outside.txt", "x"), cfg), NeedsApproval)


def test_shell_blacklist_denied():
    assert isinstance(guardrail(RunShell("rm -rf /"), _cfg()), Deny)


def test_shell_whitelist_allowed():
    assert isinstance(guardrail(RunShell("pytest -q"), _cfg()), Allow)


def test_shell_unknown_needs_approval():
    assert isinstance(guardrail(RunShell("make build"), _cfg()), NeedsApproval)


def test_read_and_tests_and_stop_allowed():
    cfg = _cfg()
    assert isinstance(guardrail(ReadFile("a.py"), cfg), Allow)
    assert isinstance(guardrail(RunTests(), cfg), Allow)
    assert isinstance(guardrail(Stop("done"), cfg), Allow)
    assert isinstance(guardrail(ListDir("."), cfg), Allow)
