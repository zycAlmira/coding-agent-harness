"""治理护栏。纯函数,确定性,可单测(无需 LLM)。

§A.4-B 核心机制:危险动作拦截 = 代码,不是提示词。
判定规则:
  - 删除文件:一律 NeedsApproval(删除是不可逆危险动作)。
  - 写文件:路径在 project_root 内 Allow;写到项目外(含 ../ 逃逸)NeedsApproval。
  - Shell:命中黑名单一律 Deny(不可放行);命中白名单 Allow;其余 NeedsApproval。
  - 只读类动作(读文件/列目录/跑测试/Stop):Allow。
"""
from __future__ import annotations

from pathlib import Path

from coding_agent_harness.config import Config
from coding_agent_harness.models import (
    Action,
    WriteFile,
    DeleteFile,
    RunShell,
    RunTests,
    ReadFile,
    ListDir,
    SearchFile,
    Stop,
    Respond,
    Allow,
    Deny,
    NeedsApproval,
)


def _is_inside(path: str, root: Path) -> bool:
    """判断 path 是否落在 root 目录内。

    对相对路径按 root 解析,再 resolve() 规范化(展开 .. / 符号链接),
    最后用 relative_to 校验是否仍在 root 下。任何 ../ 逃逸都应返回 False。
    """
    p = Path(path)
    p = p if p.is_absolute() else (root / p)
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _blacklist_hit(cmd: str, patterns: list[str]) -> bool:
    """黑名单命中判定:子串匹配(更严更安全)。

    cmd 包含 patterns 中任一项(开头或子串出现)即视为命中。
    大小写不敏感。子串匹配偏向更宽的 Deny,对黑名单是安全的——
    例如 `rm -rf` 出现在 `sudo rm -rf /` 中间也应被拦截。
    """
    c = cmd.strip().lower()
    return any(p.lower() in c for p in patterns)


def _whitelist_hit(cmd: str, patterns: list[str]) -> bool:
    """白名单命中判定:精确首词匹配(严格)。

    取 cmd 经 shlex 解析后的第一个 token(命令名),小写后是否在
    白名单 patterns(小写)集合里。这样 `pytest -q` → 首词 `pytest` ∈
    {pytest} → Allow;而 `pytest_evil --delete` → 首词 `pytest_evil` ∉
    {pytest} → 不 Allow,落入 NeedsApproval,堵住"含子串即放行"的绕过。
    """
    import shlex
    try:
        tokens = shlex.split(cmd.strip())
    except ValueError:
        # 引号不闭合等异常:宁可不放行,交审批
        return False
    if not tokens:
        return False
    first = tokens[0].lower()
    return first in {p.lower() for p in patterns}


def guardrail(action: Action, config: Config):
    """对动作作出确定性治理判定。

    纯函数,不依赖 LLM/网络/系统时间,可被单测完整覆盖。
    """
    root = config.project_root
    gr = config.guardrails
    match action:
        case DeleteFile():
            # 删除不可逆,一律审批
            return NeedsApproval(reason=f"删除: {action.path}")
        case WriteFile():
            if _is_inside(action.path, root):
                return Allow()
            return NeedsApproval(reason=f"写项目目录外: {action.path}")
        case RunShell():
            # 黑名单优先,命中即 Deny,不可被白名单或审批放行
            if _blacklist_hit(action.cmd, gr.shell_blacklist):
                return Deny(reason=f"禁止命令: {action.cmd}")
            if _whitelist_hit(action.cmd, gr.shell_whitelist):
                return Allow()
            return NeedsApproval(reason=f"执行 shell: {action.cmd}")
        case ReadFile() | ListDir() | SearchFile() | RunTests() | Stop() | Respond():
            # 只读/终止/纯文本动作放行
            return Allow()
