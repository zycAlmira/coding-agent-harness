"""工具分发。match-action,确定性,可单测。"""
from __future__ import annotations
from coding_agent_harness.config import Config
from coding_agent_harness.models import (
    Action, ReadFile, WriteFile, DeleteFile, ListDir, SearchFile, RunShell, RunTests, Stop, Respond, ToolResult,
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
        case SearchFile():
            return files.search_file(action, root)
        case RunShell():
            return shell.run_shell(action)
        case RunTests():
            # 跑测试(支持多语言 test_command),把结构化结果 PytestRun 塞进
            # ToolResult.structured,ok 由退出码判定,output 回灌 stdout 供反馈校验器解析。
            # path 可指定单文件/目录;越界路径由 run_tests 拒绝,转为错误回灌。
            try:
                tr = tests_runner.run_tests(config, action.path, action.test_command)
            except ValueError as e:
                return ToolResult(ok=False, output="", error=str(e))
            return ToolResult(ok=tr.exit_code == 0, output=tr.stdout, structured=tr, error=None)
        case Stop():
            # 停机动作:回灌 stop 标记与原因,主循环据此停机。
            return ToolResult(ok=True, output=f"stop: {action.reason}")
        case Respond():
            # 纯文本回复,无需执行,直接传递文本。
            return ToolResult(ok=True, output=action.text[:2000])
