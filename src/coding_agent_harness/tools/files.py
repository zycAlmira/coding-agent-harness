"""文件工具。path 相对 root;围栏由 guardrail 负责。"""
from __future__ import annotations
from pathlib import Path
from coding_agent_harness.models import ReadFile, WriteFile, DeleteFile, ListDir, ToolResult

# 输出最大字符数,超过则截断
MAX_OUTPUT = 8000


def _trunc(text: str) -> str:
    """超长输出截断:保留首尾各半,中间标注被截断字符数。

    截断明确告知 agent(「已截断」),否则真实 LLM 会误以为是自己读错,
    反复重读想要"完整内容"而浪费轮数(真实历史曾连续 2 轮重读被截断文件)。
    """
    if len(text) <= MAX_OUTPUT:
        return text
    head = text[: MAX_OUTPUT // 2]
    tail = text[-MAX_OUTPUT // 2 :]
    return f"{head}\n…[已截断 {len(text) - MAX_OUTPUT} 字符,文件过长,可用 offset/lines 参数分段读取]…\n{tail}"


def _resolve(path: str, root: Path) -> Path:
    """将相对路径拼到 root 下;绝对路径原样返回。"""
    p = Path(path)
    return p if p.is_absolute() else (root / p)


def read_file(action: ReadFile, root: Path) -> ToolResult:
    """读取文件文本:支持 offset/lines 按行区间读(大文件分段),超长截断;不存在则失败。

    分段读取回灌行区间进度(已读区间/总行数/剩余+建议下次 offset)——防止
    agent 反复读开头拼凑"完整内容"(真实历史曾 45+ 次重读同一文件)。
    """
    p = _resolve(action.path, root)
    try:
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        total = len(lines)
        if action.offset is not None or action.lines is not None:
            # 按行切片(offset 1-based):只取所需区间,不截断其余部分
            start = (action.offset or 1) - 1
            if action.lines is not None:
                end = start + action.lines
            else:
                end = total
            if start < 0 or start >= total:
                return ToolResult(ok=False, output="", error=f"offset 超出文件行数: {action.offset}(共 {total} 行)")
            body = "\n".join(lines[start:end])
            if start + 1 == 1 and end >= total:
                # 单段覆盖全文:无需分段
                return ToolResult(ok=True, output=f"已读 {total} 行(全文)。\n{body}")
            # 回灌进度:已读区间 + 总行数 + 建议下次 offset(避免反复读开头)
            return ToolResult(ok=True, output=(
                f"已读第 {start + 1}-{end} 行(共 {total} 行)。"
                f"如需继续读下一段,用 offset={end + 1} 参数。\n{body}"))
        # 整读:回灌总行数,便于 agent 判断是否需分段
        return ToolResult(ok=True, output=_trunc(f"(共 {total} 行)\n{text}"))
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
    """列出目录条目名,按名排序;recursive=True 时列出整个目录树(相对路径)。"""
    p = _resolve(action.path, root)
    try:
        if action.recursive:
            lines = []
            for f in sorted(p.rglob("*")):
                if f.is_file() or f.is_dir():
                    lines.append(str(f.relative_to(p)))
            return ToolResult(ok=True, output="\n".join(lines))
        names = sorted(c.name for c in p.iterdir())
        return ToolResult(ok=True, output="\n".join(names))
    except OSError as e:
        return ToolResult(ok=False, output="", error=str(e))
