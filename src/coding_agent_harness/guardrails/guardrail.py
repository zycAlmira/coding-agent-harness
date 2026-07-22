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
    Stop,
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


def _starts_with_any(cmd: str, patterns: list[str]) -> bool:
    """cmd 是否以 patterns 中任一项开头(或包含之,应对 `rm -rf` 出现在中间)。

    大小写不敏感。命中即视为匹配。
    """
    c = cmd.strip().lower()
    return any(c.startswith(p.lower()) or p.lower() in c for p in patterns)


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
            if _starts_with_any(action.cmd, gr.shell_blacklist):
                return Deny(reason=f"禁止命令: {action.cmd}")
            if _starts_with_any(action.cmd, gr.shell_whitelist):
                return Allow()
            return NeedsApproval(reason=f"执行 shell: {action.cmd}")
        case ReadFile() | ListDir() | RunTests() | Stop():
            # 只读/终止类动作放行
            return Allow()
