"""工具分发。match-action,确定性,可单测。"""
from __future__ import annotations
from coding_agent_harness.config import Config
from coding_agent_harness.models import (
    Action, ReadFile, WriteFile, DeleteFile, ListDir, RunShell, RunTests, Stop, ToolResult,
)
from coding_agent_harness.tools import files, shell, tests_runner


def dispatch(action: Action, config: Config) -> ToolResult:
    # 用 match 把 7 种 Action 分发到对应工具函数;
    # 每个分支调用确定性工具,把结果封装为 ToolResult 回灌给 agent。
    root = config.project_root
    match action:
        case ReadFile():
            return files.read_file(action, root)
        case WriteFile():
            return files.write_file(action, root)
        case DeleteFile():
            return files.delete_file(action, root)
        case ListDir():
            return files.list_dir(action, root)
        case RunShell():
            return shell.run_shell(action)
        case RunTests():
            # 跑 pytest,把结构化结果 PytestRun 塞进 ToolResult.structured,
            # ok 由退出码判定,output 回灌 stdout 供反馈校验器解析。
            tr = tests_runner.run_tests(config)
            return ToolResult(ok=tr.exit_code == 0, output=tr.stdout, structured=tr, error=None)
        case Stop():
            # 停机动作:回灌 stop 标记与原因,主循环据此停机。
            return ToolResult(ok=True, output=f"stop: {action.reason}")
