"""跑 pytest 并返回结构化结果。不判定 pass/fail。"""
from __future__ import annotations
import subprocess
import sys
import time
from coding_agent_harness.config import Config
from coding_agent_harness.models import PytestRun


def run_tests(config: Config) -> PytestRun:
    # 以子进程方式调用当前解释器的 pytest,避免路径歧义;
    # capture_output 捕获 stdout/stderr,check=False 让非零退出码不抛异常;
    # 超时 120s 防止 hang。本函数只回灌结构化结果,是否 PASS/FAIL 交给 Validator。
    root = config.project_root
    args = list(config.feedback.pytest_args)
    cmd = [sys.executable, "-m", "pytest", *args, str(root)]
    start = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    dur = time.monotonic() - start
    return PytestRun(
        exit_code=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        duration_s=dur,
    )
