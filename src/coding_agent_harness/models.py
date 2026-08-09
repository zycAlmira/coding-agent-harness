"""核心值类型。纯数据,可序列化,可单测。"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING, Union

if TYPE_CHECKING:
    # 前向引用:避免在 models 层循环 import taxonomy;validator.py 真正 import 并赋值。
    from coding_agent_harness.feedback.taxonomy import FailureCategory


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
    path: str | None = None  # 可选:只跑指定测试文件/目录(相对 project_root),None 跑全套


@dataclass(frozen=True)
class ReadFile:
    path: str
    offset: int | None = None  # 可选:起始行号(1-based,默认 1)
    lines: int | None = None   # 可选:读取行数(默认读全文,受输出截断限制)


@dataclass(frozen=True)
class ListDir:
    path: str
    recursive: bool | None = None  # 可选:true 一次列出整个目录树,避免多次逐层探索


@dataclass(frozen=True)
class Stop:
    reason: str


@dataclass(frozen=True)
class Respond:
    """LLM 输出的纯文本回复(非 tool call),用于回答问题或总结工作。"""
    text: str


# Action 联合类型:LLM 一轮可能产出的所有动作变体。
Action = Union[WriteFile, DeleteFile, RunShell, RunTests, ReadFile, ListDir, Stop, Respond]


# --- LLM 一次产出 ---
@dataclass
class AssistantTurn:
    """LLM 一次回合:解析出的动作、意图说明、原始文本。

    text: 动作伴随的文字说明(OpenAI 协议允许 content 与 tool_calls 同时返回,
    即"我先看看目录结构"这类工具调用前的说明)。Respond 动作时即回复文本。
    """
    action: Action
    intent: str
    raw: str
    text: str | None = None


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
    category: FailureCategory  # 前向引用(TYPE_CHECKING),避免循环 import
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


# --- 循环步骤与运行结果(Task 14)---
# Step:一轮完整记录(动作→护栏判定→工具结果→反馈),供回放与日志。
# RunResult:一次 agent 运行的终局产物。timestamp/ts 由调用方传入,
# 不在循环内取系统时间,保证 mock LLM 下可确定性单测。


@dataclass
class Step:
    turn: Any          # AssistantTurn
    verdict: Any       # Verdict
    tool_result: Any   # ToolResult | None
    feedback: Any      # Feedback | None
    ts: str            # 由调用方传入


@dataclass
class RunResult:
    outcome: str       # Outcome 值
    steps: list
    final_feedback: Any = None
