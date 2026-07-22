"""核心值类型。纯数据,可序列化,可单测。"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Union


# --- 运行结果枚举 ---
class Outcome(str, Enum):
    """agent 一次运行的终局状态。"""
    SUCCESS = "success"
    STUCK = "stuck"
    MAX_ROUNDS = "max_rounds"
    STOPPED = "stopped"
    ERROR = "error"


# --- 动作(来自 LLM) ---
# 使用 frozen dataclass 让动作值对象不可变,便于比对与回放。
@dataclass(frozen=True)
class WriteFile:
    path: str
    content: str


@dataclass(frozen=True)
class DeleteFile:
    path: str


@dataclass(frozen=True)
class RunShell:
    cmd: str


@dataclass(frozen=True)
class RunTests:
    pass


@dataclass(frozen=True)
class ReadFile:
    path: str


@dataclass(frozen=True)
class ListDir:
    path: str


@dataclass(frozen=True)
class Stop:
    reason: str


# Action 联合类型:LLM 一轮可能产出的所有动作变体。
Action = Union[WriteFile, DeleteFile, RunShell, RunTests, ReadFile, ListDir, Stop]


# --- LLM 一次产出 ---
@dataclass
class AssistantTurn:
    """LLM 一次回合:解析出的动作、意图说明、原始文本。"""
    action: Action
    intent: str
    raw: str


# --- 护栏判定 ---
# Verdict 为基类,Allow/Deny/NeedsApproval 为具体判定。
# 子类的 reason 使用 kw_only,避免「非默认参数跟在默认参数之后」的 dataclass 顺序错误
# (基类 is_approval 带默认值,子类无默认值的 reason 若按位置排会非法)。
@dataclass
class Verdict:
    is_approval: bool = False


@dataclass
class Allow(Verdict):
    # 允许执行,无需人工审批
    is_approval: bool = False


@dataclass
class Deny(Verdict):
    # 直接拒绝,携带原因
    reason: str = field(kw_only=True)


@dataclass
class NeedsApproval(Verdict):
    # 需要人工审批,携带原因
    reason: str = field(kw_only=True)
    is_approval: bool = True


# --- 工具结果 ---
@dataclass
class PytestRun:
    """一次 pytest 执行的结构化结果。"""
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float


@dataclass
class ToolResult:
    """工具执行回灌给 agent 的通用结果封装。"""
    ok: bool
    output: str
    structured: PytestRun | None = None
    error: str | None = None


# 备注:Fix/Step/RunResult 留到 Task 9/15 定义,
# 避免本 task 引入未使用的前向依赖类型。


# --- 反馈校验器产物(Task 5)---
# FailedTest / Feedback:解析 pytest 输出得到结构化反馈,供反馈闭环回灌给 agent。
# category 用字符串注解作前向引用,避免在 models 层循环 import taxonomy;
# validator.py 真正 import FailureCategory 并赋值。
@dataclass
class FailedTest:
    nodeid: str
    category: "FailureCategory"  # 前向引用,避免循环 import
    file: str
    line: int
    traceback_excerpt: str
    assertion_diff: str | None = None


@dataclass
class Feedback:
    status: str  # "PASS" | "FAIL"
    failed_tests: list[FailedTest]
    passed_count: int
    summary: str


# --- 记忆 store 产物(Task 10)---
# Fix:一条修复经验,按 FailureCategory 值索引。timestamp 由调用方传入,
# 不在循环内取系统时间(保证 mock LLM 下可确定性地单测)。
@dataclass
class Fix:
    category: str   # FailureCategory 值
    symptom: str
    fix: str
    timestamp: str  # ISO 字符串,由调用方传入(不在循环内取系统时间)
