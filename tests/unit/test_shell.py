import sys
from coding_agent_harness.models import RunShell
from coding_agent_harness.tools.shell import run_shell


def _echo_cmd():
    # 跨平台:用 sys.executable 跑 python -c
    return f'"{sys.executable}" -c "print(42)"'


def test_run_shell_captures_output():
    r = run_shell(RunShell(_echo_cmd()))
    assert r.ok
    assert "42" in r.output


def test_run_shell_nonzero_exit():
    r = run_shell(RunShell(f'"{sys.executable}" -c "import sys; sys.exit(3)"'))
    assert not r.ok
    assert r.error


def test_run_shell_timeout():
    loop = f'"{sys.executable}" -c "import time; time.sleep(5)"'
    r = run_shell(RunShell(loop), timeout=1)
    assert not r.ok
    assert "timeout" in r.error.lower()
