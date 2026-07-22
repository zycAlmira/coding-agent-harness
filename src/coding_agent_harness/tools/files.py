"""文件工具。path 相对 root;围栏由 guardrail 负责。"""
from __future__ import annotations
from pathlib import Path
from coding_agent_harness.models import ReadFile, WriteFile, DeleteFile, ListDir, ToolResult

# 输出最大字符数,超过则截断
MAX_OUTPUT = 8000


def _trunc(text: str) -> str:
    """超长输出截断:保留首尾各半,中间标注被截断字符数。"""
    if len(text) <= MAX_OUTPUT:
        return text
    head = text[: MAX_OUTPUT // 2]
    tail = text[-MAX_OUTPUT // 2 :]
    return f"{head}\n...[truncated {len(text) - MAX_OUTPUT} chars]...\n{tail}"


def _resolve(path: str, root: Path) -> Path:
    """将相对路径拼到 root 下;绝对路径原样返回。"""
    p = Path(path)
    return p if p.is_absolute() else (root / p)


def read_file(action: ReadFile, root: Path) -> ToolResult:
    """读取文件文本,超长截断;不存在则失败。"""
    p = _resolve(action.path, root)
    try:
        return ToolResult(ok=True, output=_trunc(p.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return ToolResult(ok=False, output="", error=f"文件不存在: {action.path}")
    except OSError as e:
        return ToolResult(ok=False, output="", error=str(e))


def write_file(action: WriteFile, root: Path) -> ToolResult:
    """写入文件文本,父目录自动创建。"""
    p = _resolve(action.path, root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(action.content, encoding="utf-8")
        return ToolResult(ok=True, output=f"written {action.path} ({len(action.content)} chars)")
    except OSError as e:
        return ToolResult(ok=False, output="", error=str(e))


def delete_file(action: DeleteFile, root: Path) -> ToolResult:
    """删除文件或空目录;不存在则失败。"""
    p = _resolve(action.path, root)
    try:
        if p.is_dir():
            # 只删空目录;非空目录需护栏审批后显式删
            p.rmdir()
        else:
            p.unlink()
        return ToolResult(ok=True, output=f"deleted {action.path}")
    except FileNotFoundError:
        return ToolResult(ok=False, output="", error=f"不存在: {action.path}")
    except OSError as e:
        return ToolResult(ok=False, output="", error=str(e))


def list_dir(action: ListDir, root: Path) -> ToolResult:
    """列出目录条目名,按名排序。"""
    p = _resolve(action.path, root)
    try:
        names = sorted(c.name for c in p.iterdir())
        return ToolResult(ok=True, output="\n".join(names))
    except OSError as e:
        return ToolResult(ok=False, output="", error=str(e))
