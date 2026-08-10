"""跑 pytest 并返回结构化结果。不判定 pass/fail。"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from coding_agent_harness.config import Config
from coding_agent_harness.models import PytestRun


def _clear_bytecode_cache(root: Path) -> None:
    """清除 root 下所有 __pycache__ 目录。

    必要性:agent 循环可能在一秒内多次改写源文件再跑测试。Python 的 .pyc
    字节码缓存按源文件 mtime 判定有效性,而常见文件系统 mtime 精度为 1 秒;
    同一秒内的改写会使 mtime 不变,Python 误判旧 .pyc 仍有效,从而导入到
    上一轮的旧字节码——反馈闭环的"改了却没生效"假象,破坏确定性(§A.4)。
    每次跑测试前清掉 __pycache__,保证每次都重新读源文件、按当前内容判定。
    """
    for pyc in root.rglob("__pycache__"):
        try:
            shutil.rmtree(pyc)
        except OSError:
            # 并发或权限问题不影响主流程;最坏情况 pytest 仍会按 mtime 重编译。
            pass


def run_tests(config: Config, path: str | None = None, test_command: str | None = None) -> PytestRun:
    # 以子进程方式调用测试命令;capture_output 捕获 stdout/stderr,
    # check=False 让非零退出码不抛异常;超时 120s 防止 hang。
    # 本函数只回灌结构化结果,是否 PASS/FAIL 交给 Validator。
    # test_command 支持 pytest(默认)/mvn test/npm test/go test 等多语言测试。
    root = config.project_root
    _clear_bytecode_cache(root)
    if test_command:
        # 自定义测试命令:交给 shell 执行(构建命令在白名单内由护栏管控)
        cmd = f"{test_command} {path or ''}".strip()
    else:
        args = list(config.feedback.pytest_args)
        if path:
            # 安全边界:测试路径必须落在 project_root 内,防 ../ 逃逸(同文件工具围栏)
            target = (root / path).resolve()
            if not target.is_relative_to(root.resolve()):
                raise ValueError(f"测试路径越界: {path}")
            target = str(target)
        else:
            target = str(root)
        cmd = [sys.executable, "-m", "pytest", *args, target]
    env = dict(os.environ)
    # 不再写 .pyc:配合每次跑前清缓存,彻底杜绝亚秒级 mtime 冲突导致的旧字节码命中。
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    start = time.monotonic()
    # test_command 是字符串命令(含空格),用 shell=True;pytest 走 list(无 shell)
    use_shell = isinstance(cmd, str)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False, env=env, shell=use_shell)
    dur = time.monotonic() - start
    return PytestRun(
        exit_code=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        duration_s=dur,
    )
