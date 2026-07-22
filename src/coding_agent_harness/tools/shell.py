"""跨平台 shell 执行。shell=False,用 shlex 拆参。"""
from __future__ import annotations
import shlex
import subprocess
import sys
from coding_agent_harness.models import RunShell, ToolResult

# 输出截断上限(字符数),避免超长输出污染上下文。
MAX_OUTPUT = 8000


def _trunc(text: str) -> str:
    """超长输出截断,附加被截断字符数提示。"""
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n...[truncated {len(text) - MAX_OUTPUT} chars]..."


def run_shell(action: RunShell, timeout: int = 30) -> ToolResult:
    # Windows 上 shlex 对反斜杠路径处理弱;对含引号包裹的路径用 posix=False
    is_win = sys.platform.startswith("win")
    argv = shlex.split(action.cmd, posix=not is_win)
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, output="", error="timeout")
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=f"command not found: {e}")
    out = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0
    return ToolResult(
        ok=ok,
        output=_trunc(out),
        error=None if ok else f"exit {proc.returncode}",
    )
