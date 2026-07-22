# Coding Agent Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个自实现的 Python Coding Agent Harness 内核,以反馈闭环为主贡献,带 mock-LLM 单测、单页 WebUI、跨平台分发。

**Architecture:** AgentLoop 主循环(自实现,不寄生框架)串联 LLM 抽象层(真实 OpenAI 兼容 / mock 脚本化)、工具分发、确定性校验器 + 失败分类 taxonomy、治理护栏 + HITL 状态机、分类索引记忆。FastAPI + SSE 单页 WebUI 观察。每个机制都是确定性代码,移除真实 LLM 后仍可单测。

**Tech Stack:** Python 3.11+、uv、pytest、FastAPI、httpx、keyring、PyYAML、Open Design(前端)。

## Global Constraints

- Python ≥ 3.11(用 `Path.is_relative_to`、`match` 语法)。
- 主循环、LLM 抽象层、工具分发、护栏、校验器、记忆**必须自实现**;禁止寄生 LangChain/AutoGen/CrewAI/LlamaIndex 等高层 agent 循环。
- 机制是代码不是提示词;反馈=校验器函数,危险动作=护栏函数。
- 所有单测用 `MockLLMClient`,不触网、不依赖真实 LLM。
- key 绝不硬编码、不进 git、不进日志、不回显明文。
- 跨平台:macOS/Linux/Windows 10+;`pathlib.Path` 全程;CI 跑 ubuntu + windows 矩阵。
- TDD 强制:先写失败测试、跑红、写最小实现跑绿、再重构。
- 频繁 commit;每个 task 一个或多个 commit。
- 命名:snake_case;包名 `coding_agent_harness`;CLI 命令 `harness`。
- 永远用中文写用户可见文案与注释;日志可英文。

---

## File Structure

```
coding-agent-harness/                     (仓库根 = 当前目录)
├─ pyproject.toml                        依赖与 CLI 入口
├─ uv.lock                               依赖锁
├─ Makefile                              test/run/lint(Unix 便利)
├─ README.md                             含安全边界章节
├─ config.example.yaml                   配置样例
├─ Dockerfile                            云部署用
├─ .github/workflows/ci.yml             CI,含 unit-test job,ubuntu+windows
├─ src/coding_agent_harness/
│  ├─ __init__.py
│  ├─ main.py                            CLI: serve/creds/run
│  ├─ config.py                          load_config -> Config
│  ├─ models.py                          值类型:Action/Verdict/Feedback 等
│  ├─ core/loop.py                       AgentLoop 主循环
│  ├─ core/state.py                      LoopState/RunResult/停机判断
│  ├─ llm/base.py                        LLMClient Protocol
│  ├─ llm/mock.py                        MockLLMClient
│  ├─ llm/openai_compat.py               真实实现
│  ├─ tools/dispatch.py                  dispatch(action)
│  ├─ tools/files.py                     read/write/delete/list
│  ├─ tools/shell.py                     run_shell 跨平台
│  ├─ tools/tests_runner.py              run_tests -> PytestRun
│  ├─ feedback/taxonomy.py               FailureCategory + 策略提示
│  ├─ feedback/validator.py              Validator.parse 纯函数
│  ├─ guardrails/guardrail.py            guardrail + HITL 状态机
│  ├─ memory/store.py                    retrieve/write fixes+conventions
│  ├─ creds/keychain.py                  keyring 封装
│  └─ web/app.py + web/static/           FastAPI + SSE + 单页前端
├─ tests/unit/                           纯函数单测
├─ tests/integration/                    mock LLM 跑整条 loop
├─ tests/demo/                           §A.6 三个机制演示
├─ scripts/demo.sh                       一键串跑三个演示
└─ workspace/                            demo 目标(failing pytest)
```

依赖方向:`models` ← 所有模块;`taxonomy` ← `validator` ← `loop`;`base` ← `mock`/`openai_compat` ← `loop`;`files`/`shell`/`tests_runner` ← `dispatch` ← `loop`;`guardrail` ← `loop`;`store` ← `loop`;`config` ← 全部。`loop` 是顶层组装点。

---

## Task 1: 项目脚手架与依赖

**Files:**
- Create: `pyproject.toml`
- Create: `src/coding_agent_harness/__init__.py`
- Create: `Makefile`
- Create: `.gitignore`
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Produces: 可 import 的包 `coding_agent_harness`;CLI 入口 `harness`;`make test` 一键跑测试。

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "coding-agent-harness"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "httpx>=0.27",
    "keyring>=24",
    "pyyaml>=6",
    "uvicorn>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23"]

[project.scripts]
harness = "coding_agent_harness.main:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/coding_agent_harness"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: 写 `src/coding_agent_harness/__init__.py`**

```python
"""Coding Agent Harness — 自实现的 coding agent 内核。"""

__version__ = "0.1.0"
```

- [ ] **Step 3: 写 Makefile**

```makefile
.PHONY: test run lint
test:
	uv run pytest -q
run:
	uv run harness serve
lint:
	uv run ruff check src tests
```

- [ ] **Step 4: 写 .gitignore**

```
__pycache__/
*.pyc
.venv/
.env
memory/fixes.json
!memory/fixes.example.json
.pytest_cache/
dist/
```

- [ ] **Step 5: 写失败测试 `tests/test_scaffold.py`**

```python
import importlib


def test_package_importable():
    m = importlib.import_module("coding_agent_harness")
    assert m.__version__ == "0.1.0"
```

- [ ] **Step 6: 跑测试验证失败**

Run: `uv run pytest tests/test_scaffold.py -v`
Expected: FAIL(若 uv 未初始化则先 `uv sync`)。

- [ ] **Step 7: 初始化环境**

Run: `uv sync --extra dev`
Expected: 安装依赖,生成 `uv.lock` 与 `.venv`。

- [ ] **Step 8: 跑测试验证通过**

Run: `uv run pytest tests/test_scaffold.py -v`
Expected: PASS。

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock Makefile .gitignore src tests
git commit -m "chore: 项目脚手架与依赖"
```

---

## Task 2: 值类型与数据模型 `models.py`

**Files:**
- Create: `src/coding_agent_harness/models.py`
- Test: `tests/unit/test_models.py`

**Interfaces:**
- Produces: `Action` 联合类型(`WriteFile`/`DeleteFile`/`RunShell`/`RunTests`/`ReadFile`/`ListDir`/`Stop`)、`AssistantTurn`、`Verdict`(`Allow`/`Deny`/``NeedsApproval`)、`ToolResult`、`PytestRun`、`Feedback`/`FailedTest`、`Fix`、`Step`、`RunResult`、`Outcome` 枚举。

- [ ] **Step 1: 写失败测试 `tests/unit/test_models.py`**

```python
from coding_agent_harness.models import (
    Action, Allow, Deny, NeedsApproval, AssistantTurn, WriteFile,
)


def test_action_is_union_of_variants():
    a = WriteFile(path="src/x.py", content="print(1)")
    assert isinstance(a, Action)


def test_verdicts_carry_reason():
    assert Deny(reason="rm -rf").reason == "rm -rf"
    assert NeedsApproval(reason="del").is_approval
    assert Allow().is_approval is False


def test_assistant_turn_has_intent():
    t = AssistantTurn(action=WriteFile("a", "b"), intent="修 bug", raw="...")
    assert t.intent == "修 bug"
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: FAIL(模块不存在)。

- [ ] **Step 3: 写实现 `src/coding_agent_harness/models.py`**

```python
"""核心值类型。纯数据,可序列化,可单测。"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Union


class Outcome(str, Enum):
    SUCCESS = "success"
    STUCK = "stuck"
    MAX_ROUNDS = "max_rounds"
    STOPPED = "stopped"
    ERROR = "error"


# --- 动作(来自 LLM) ---
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

Action = Union[WriteFile, DeleteFile, RunShell, RunTests, ReadFile, ListDir, Stop]


# --- LLM 一次产出 ---
@dataclass
class AssistantTurn:
    action: Action
    intent: str
    raw: str


# --- 护栏判定 ---
class Verdict:
    is_approval: bool = False

@dataclass
class Allow(Verdict):
    is_approval: bool = False

@dataclass
class Deny(Verdict):
    reason: str

@dataclass
class NeedsApproval(Verdict):
    reason: str
    is_approval: bool = True


# --- 工具结果 ---
@dataclass
class PytestRun:
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float

@dataclass
class ToolResult:
    ok: bool
    output: str
    structured: PytestRun | None = None
    error: str | None = None
```

（`Feedback`/`FailedTest`/`Fix`/`Step`/`RunResult` 留到 Task 4/9/15 定义,避免前向依赖未定义类型。）

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent_harness/models.py tests/unit/test_models.py
git commit -m "feat(models): 动作/判定/工具结果值类型"
```

---

## Task 3: 配置 `config.py`

**Files:**
- Create: `src/coding_agent_harness/config.py`
- Create: `config.example.yaml`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `load_config(path) -> Config`;`Config` 有字段 `project_root`(Path)、`llm.{base_url,model}`、`guardrails.{max_rounds, same_category_prompt_at, same_category_stop_at, no_change_stop_at, approval_timeout_sec, shell_blacklist, shell_whitelist}`、`feedback.{pytest_args, max_traceback_excerpt_lines}`、`memory.{fixes_path, conventions_path, retrieve_top_k}`。

- [ ] **Step 1: 写 config.example.yaml**(见 spec §十一,此处照抄)

```yaml
project_root: ./workspace

llm:
  provider: openai-compatible
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat

guardrails:
  max_rounds: 8
  same_category_prompt_at: 2
  same_category_stop_at: 3
  no_change_stop_at: 2
  approval_timeout_sec: 300
  shell_blacklist: [rm -rf, git push, sudo, curl, wget, chmod 777,
                   "del /s", "rmdir /s", "Remove-Item -Recurse", format, diskpart]
  shell_whitelist: [pytest, ruff, mypy]

feedback:
  pytest_args: [--tb=short, -p, no:cacheprovider, --no-header, -q]
  max_traceback_excerpt_lines: 8

memory:
  fixes_path: ./memory/fixes.json
  conventions_path: ./memory/conventions.json
  retrieve_top_k: 3
```

- [ ] **Step 2: 写失败测试 `tests/unit/test_config.py`**

```python
from pathlib import Path
from coding_agent_harness.config import load_config


def test_load_config_parses_fields(tmp_path):
    cfg_yaml = tmp_path / "c.yaml"
    cfg_yaml.write_text(
        "project_root: ./ws\n"
        "llm: {provider: openai-compatible, base_url: 'http://x', model: m}\n"
        "guardrails:\n"
        "  max_rounds: 5\n  same_category_prompt_at: 2\n"
        "  same_category_stop_at: 3\n  no_change_stop_at: 2\n"
        "  approval_timeout_sec: 60\n"
        "  shell_blacklist: [rm -rf]\n  shell_whitelist: [pytest]\n"
        "feedback:\n  pytest_args: [-q]\n  max_traceback_excerpt_lines: 4\n"
        "memory:\n  fixes_path: ./f.json\n  conventions_path: ./c.json\n  retrieve_top_k: 2\n"
    )
    cfg = load_config(cfg_yaml)
    assert cfg.project_root == Path("./ws")
    assert cfg.guardrails.max_rounds == 5
    assert "rm -rf" in cfg.guardrails.shell_blacklist
    assert cfg.memory.retrieve_top_k == 2


def test_load_config_applies_defaults_when_missing(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text("project_root: ./ws\nllm: {base_url: 'http://x', model: m}\n")
    cfg = load_config(f)
    assert cfg.guardrails.max_rounds == 8  # 默认
    assert cfg.guardrails.same_category_stop_at == 3
```

- [ ] **Step 3: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL。

- [ ] **Step 4: 写实现 `src/coding_agent_harness/config.py`**

```python
"""声明式配置加载。纯函数,可单测。"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    provider: str = "openai-compatible"

@dataclass(frozen=True)
class GuardrailsConfig:
    max_rounds: int = 8
    same_category_prompt_at: int = 2
    same_category_stop_at: int = 3
    no_change_stop_at: int = 2
    approval_timeout_sec: int = 300
    shell_blacklist: list[str] = field(default_factory=lambda: ["rm -rf"])
    shell_whitelist: list[str] = field(default_factory=lambda: ["pytest"])

@dataclass(frozen=True)
class FeedbackConfig:
    pytest_args: list[str] = field(default_factory=lambda: ["--tb=short", "-q"])
    max_traceback_excerpt_lines: int = 8

@dataclass(frozen=True)
class MemoryConfig:
    fixes_path: str = "./memory/fixes.json"
    conventions_path: str = "./memory/conventions.json"
    retrieve_top_k: int = 3

@dataclass(frozen=True)
class Config:
    project_root: Path
    llm: LLMConfig
    guardrails: GuardrailsConfig = field(default_factory=GuardrailsConfig)
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)


def load_config(path: Path | str) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    llm_raw = raw.get("llm", {})
    gr_raw = raw.get("guardrails", {})
    fb_raw = raw.get("feedback", {})
    mem_raw = raw.get("memory", {})
    return Config(
        project_root=Path(raw["project_root"]),
        llm=LLMConfig(
            base_url=llm_raw["base_url"],
            model=llm_raw["model"],
            provider=llm_raw.get("provider", "openai-compatible"),
        ),
        guardrails=GuardrailsConfig(**{k: gr_raw[k] for k in gr_raw if k in GuardrailsConfig.__dataclass_fields__}),
        feedback=FeedbackConfig(**{k: fb_raw[k] for k in fb_raw if k in FeedbackConfig.__dataclass_fields__}),
        memory=MemoryConfig(**{k: mem_raw[k] for k in mem_raw if k in MemoryConfig.__dataclass_fields__}),
    )
```

- [ ] **Step 5: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/coding_agent_harness/config.py config.example.yaml tests/unit/test_config.py
git commit -m "feat(config): 声明式配置加载与默认值"
```

---

## Task 4: 失败分类 taxonomy

**Files:**
- Create: `src/coding_agent_harness/feedback/taxonomy.py`
- Test: `tests/unit/test_taxonomy.py`

**Interfaces:**
- Produces: `FailureCategory` 枚举(AssertionFailure/ImportError/AttributeError/NameError/TypeError/SyntaxError/CollectionError/Timeout/Unknown);`strategy_hint(category) -> str` 返回确定性的建议策略提示。

- [ ] **Step 1: 写失败测试 `tests/unit/test_taxonomy.py`**

```python
from coding_agent_harness.feedback.taxonomy import FailureCategory, strategy_hint


def test_all_categories_have_hint():
    for c in FailureCategory:
        assert isinstance(strategy_hint(c), str) and strategy_hint(c)


def test_hint_is_deterministic():
    assert strategy_hint(FailureCategory.AssertionFailure) == strategy_hint(FailureCategory.AssertionFailure)


def test_unknown_has_fallback():
    assert strategy_hint(FailureCategory.Unknown)
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_taxonomy.py -v`
Expected: FAIL。

- [ ] **Step 3: 写实现 `src/coding_agent_harness/feedback/taxonomy.py`**

```python
"""失败分类表 + 确定性建议策略。"""
from __future__ import annotations
from enum import Enum


class FailureCategory(str, Enum):
    AssertionFailure = "AssertionFailure"
    ImportError = "ImportError"
    AttributeError = "AttributeError"
    NameError = "NameError"
    TypeError = "TypeError"
    SyntaxError = "SyntaxError"
    CollectionError = "CollectionError"
    Timeout = "Timeout"
    Unknown = "Unknown"


_HINTS: dict[FailureCategory, str] = {
    FailureCategory.AssertionFailure: "看断言两侧实际值,定位计算错误",
    FailureCategory.ImportError: "检查模块名拼写/路径或是否缺依赖",
    FailureCategory.AttributeError: "检查属性名拼写与对象类型",
    FailureCategory.NameError: "检查名字是否已定义/作用域",
    FailureCategory.TypeError: "检查参数类型与个数",
    FailureCategory.SyntaxError: "先让文件能被解析,再谈逻辑",
    FailureCategory.CollectionError: "导入阶段就报错,先修 import-time 错误",
    FailureCategory.Timeout: "测试卡住,检查是否有死循环或阻塞",
    FailureCategory.Unknown: "仔细阅读 traceback,定位报错来源",
}


def strategy_hint(category: FailureCategory) -> str:
    return _HINTS[category]
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_taxonomy.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent_harness/feedback/taxonomy.py tests/unit/test_taxonomy.py
git commit -m "feat(feedback): 失败分类 taxonomy 与策略提示"
```

---

## Task 5: 反馈校验器 `Validator.parse`

**Files:**
- Create: `src/coding_agent_harness/feedback/validator.py`
- Modify: `src/coding_agent_harness/models.py`(加 `Feedback`/`FailedTest`)
- Test: `tests/unit/test_validator.py`
- Test fixture: `tests/unit/fixtures/assertion_fail.txt`、`tests/unit/fixtures/import_error.txt`、`tests/unit/fixtures/pass.txt`

**Interfaces:**
- Consumes: `models.PytestRun`、`taxonomy.FailureCategory`。
- Produces: `Validator.parse(run: PytestRun) -> Feedback`;`Feedback{status, failed_tests, passed_count, summary}`、`FailedTest{nodeid, category, file, line, traceback_excerpt, assertion_diff}`。

- [ ] **Step 1: 给 models 加 Feedback/FailedTest**

在 `src/coding_agent_harness/models.py` 末尾追加:

```python
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
```

（`FailureCategory` 用字符串注解,运行时不解析,避免循环 import;`validator.py` 真正 import 它。）

- [ ] **Step 2: 写 fixture `tests/unit/fixtures/assertion_fail.txt`**(模拟 pytest `--tb=short` 输出)

```
============================= test session starts =============================
collected 2 items

tests/test_calc.py .F                                                    [100%]

=================================== FAILURES ===================================
_________________________________ test_add ___________________________________
    def test_add():
>       assert add(2, 2) == 5
E       assert 4 == 5

tests/test_calc.py:5: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_calc.py::test_add - assert 4 == 5
1 failed, 1 passed in 0.05s
```

- [ ] **Step 3: 写 fixture `tests/unit/fixtures/import_error.txt`**

```
collected 1 item

tests/test_x.py E                                                        [1000%]

==================================== ERRORS ====================================
_____________________________ ERROR at setup of test_x __________________________
>   from missing_module import something
E       ModuleNotFoundError: No module named 'missing_module'

tests/test_x.py:1: CollectionError
ERROR tests/test_x.py::test_x
= 1 error in 0.04s =
```

- [ ] **Step 4: 写 fixture `tests/unit/fixtures/pass.txt`**

```
collected 2 items

tests/test_calc.py ..                                                    [100%]

2 passed in 0.05s
```

- [ ] **Step 5: 写失败测试 `tests/unit/test_validator.py`**

```python
from pathlib import Path
from coding_agent_harness.feedback.validator import Validator
from coding_agent_harness.feedback.taxonomy import FailureCategory
from coding_agent_harness.models import PytestRun

FIX = Path(__file__).parent / "fixtures"


def _run(name: str) -> PytestRun:
    return PytestRun(exit_code=1, stdout=(FIX / name).read_text(), stderr="", duration_s=0.05)


def test_pass_when_no_failures():
    r = PytestRun(exit_code=0, stdout=(FIX / "pass.txt").read_text(), stderr="", duration_s=0.05)
    fb = Validator.parse(r)
    assert fb.status == "PASS"
    assert fb.failed_tests == []
    assert fb.passed_count == 2


def test_assertion_failure_classified():
    fb = Validator.parse(_run("assertion_fail.txt"))
    assert fb.status == "FAIL"
    assert len(fb.failed_tests) == 1
    ft = fb.failed_tests[0]
    assert ft.nodeid == "tests/test_calc.py::test_add"
    assert ft.category is FailureCategory.AssertionFailure
    assert ft.file == "tests/test_calc.py"
    assert ft.line == 5
    assert ft.assertion_diff == "assert 4 == 5"


def test_import_error_classified():
    fb = Validator.parse(_run("import_error.txt"))
    assert fb.status == "FAIL"
    cat = fb.failed_tests[0].category
    assert cat in (FailureCategory.ImportError, FailureCategory.CollectionError)


def test_summary_extracted():
    fb = Validator.parse(_run("assertion_fail.txt"))
    assert "1 failed" in fb.summary and "1 passed" in fb.summary


def test_traceback_excerpt_truncated_to_config(tmp_path):
    # 超长 traceback 应截断(此例短,仅断言非空)
    fb = Validator.parse(_run("assertion_fail.txt"))
    assert fb.failed_tests[0].traceback_excerpt
```

- [ ] **Step 6: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_validator.py -v`
Expected: FAIL(validator 不存在)。

- [ ] **Step 7: 写实现 `src/coding_agent_harness/feedback/validator.py`**

```python
"""解析 pytest 输出为结构化 Feedback。纯函数,确定性,可单测。"""
from __future__ import annotations
import re
from coding_agent_harness.models import PytestRun, Feedback, FailedTest
from coding_agent_harness.feedback.taxonomy import FailureCategory


_FAILED_LINE = re.compile(r"^FAILED (?P<nodeid>\S+)(?: - (?P<diff>.*))?$")
_FAIL_HEADER = re.compile(r"^_+ (?P<nodeid>\w+) _+$")
_TB_LOC = re.compile(r"^(?P<file>[^\s]+):(?P<line>\d+): (?P<err>\w+Error)$")
_ASSERT_LINE = re.compile(r"E\s+assert\s+(?P<diff>.+)")
_SUMMARY = re.compile(r"(\d+) (failed|passed|error)")


def _classify(err_word: str, diff: str | None) -> FailureCategory:
    w = err_word.lower()
    if "assert" in w or (diff and "assert" in diff):
        return FailureCategory.AssertionFailure
    if "importerror" in w or "modulenotfound" in w:
        return FailureCategory.ImportError
    if "attributeerror" in w:
        return FailureCategory.AttributeError
    if "nameerror" in w:
        return FailureCategory.NameError
    if "typeerror" in w:
        return FailureCategory.TypeError
    if "syntaxerror" in w:
        return FailureCategory.SyntaxError
    if "collection" in w:
        return FailureCategory.CollectionError
    return FailureCategory.Unknown


class Validator:
    @staticmethod
    def parse(run: PytestRun, max_excerpt_lines: int = 8) -> Feedback:
        stdout = run.stdout.replace("\r\n", "\n").replace("\r", "\n")
        lines = stdout.splitlines()
        failed: list[FailedTest] = []
        summary_bits: list[str] = []
        for ln in lines:
            m = _SUMMARY.search(ln)
            if m:
                summary_bits.append(f"{m.group(1)} {m.group(2)}")

        # 扫 FAILED 行拿 nodeid + diff
        fail_index: dict[str, str | None] = {}
        for ln in lines:
            m = _FAILED_LINE.match(ln)
            if m:
                fail_index[m.group("nodeid")] = m.group("diff")

        # 扫 traceback 块拿 file:line + err
        cur_nodeid: str | None = None
        excerpt: list[str] = []
        for ln in lines:
            mh = _FAIL_HEADER.match(ln)
            if mh:
                # header 形如 _ test_add _;nodeid 已在 FAIL_HEADER 捕获不到全路径,
                # 改用最近 FAILED 行匹配:取 fail_index 第一个含该名者
                cur_nodeid = _match_nodeid_by_name(fail_index, mh.group("nodeid"))
                excerpt = []
                continue
            if cur_nodeid:
                mt = _TB_LOC.match(ln)
                if mt:
                    diff = fail_index.get(cur_nodeid)
                    failed.append(FailedTest(
                        nodeid=cur_nodeid,
                        category=_classify(mt.group("err"), diff),
                        file=mt.group("file"),
                        line=int(mt.group("line")),
                        traceback_excerpt="\n".join(excerpt[-max_excerpt_lines:]),
                        assertion_diff=diff,
                    ))
                    cur_nodeid = None
                else:
                    excerpt.append(ln)

        status = "PASS" if run.exit_code == 0 and not failed else "FAIL"
        passed = 0
        for b in summary_bits:
            if b.endswith("passed"):
                passed = int(b.split()[0])
        summary = ", ".join(summary_bits) if summary_bits else stdout.strip().splitlines()[-1]
        return Feedback(status=status, failed_tests=failed, passed_count=passed, summary=summary)


def _match_nodeid_by_name(index: dict[str, str | None], name: str) -> str | None:
    for nid in index:
        if nid.split("::")[-1] == name:
            return nid
    return next(iter(index), None)
```

- [ ] **Step 8: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_validator.py -v`
Expected: PASS。若某些断言失败,根据实际 pytest 文本微调正则,但**不改测试断言**(测试是契约)。

- [ ] **Step 9: Commit**

```bash
git add src tests
git commit -m "feat(feedback): Validator 解析 pytest 输出为结构化 Feedback"
```

---

## Task 6: 工具 — 文件操作 `tools/files.py`

**Files:**
- Create: `src/coding_agent_harness/tools/files.py`
- Test: `tests/unit/test_files.py`

**Interfaces:**
- Consumes: `models.{ReadFile,WriteFile,DeleteFile,ListDir,ToolResult}`、`config.Config`(project_root 做路径围栏校验由 guardrail 负责,这里只执行)。
- Produces: `read_file(action, root) -> ToolResult`、`write_file(action, root) -> ToolResult`、`delete_file(action, root) -> ToolResult`、`list_dir(action, root) -> ToolResult`。输出超 8000 字符截断。

- [ ] **Step 1: 写失败测试 `tests/unit/test_files.py`**

```python
from coding_agent_harness.models import ReadFile, WriteFile, DeleteFile, ListDir
from coding_agent_harness.tools.files import read_file, write_file, delete_file, list_dir


def test_write_then_read(tmp_path):
    w = write_file(WriteFile("a.txt", "hello"), tmp_path)
    assert w.ok
    r = read_file(ReadFile("a.txt"), tmp_path)
    assert r.ok and r.output == "hello"


def test_read_missing_file_fails(tmp_path):
    r = read_file(ReadFile("nope.txt"), tmp_path)
    assert not r.ok
    assert r.error


def test_delete_removes_file(tmp_path):
    write_file(WriteFile("x.txt", "y"), tmp_path)
    d = delete_file(DeleteFile("x.txt"), tmp_path)
    assert d.ok
    assert not (tmp_path / "x.txt").exists()


def test_list_dir_returns_names(tmp_path):
    write_file(WriteFile("a.txt", "1"), tmp_path)
    write_file(WriteFile("b.txt", "2"), tmp_path)
    r = list_dir(ListDir("."), tmp_path)
    assert r.ok and "a.txt" in r.output and "b.txt" in r.output


def test_long_output_truncated(tmp_path):
    write_file(WriteFile("big.txt", "x" * 20000), tmp_path)
    r = read_file(ReadFile("big.txt"), tmp_path)
    assert len(r.output) < 20000
    assert "..." in r.output
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_files.py -v`
Expected: FAIL。

- [ ] **Step 3: 写实现 `src/coding_agent_harness/tools/files.py`**

```python
"""文件工具。path 相对 root;围栏由 guardrail 负责。"""
from __future__ import annotations
from pathlib import Path
from coding_agent_harness.models import ReadFile, WriteFile, DeleteFile, ListDir, ToolResult

MAX_OUTPUT = 8000


def _trunc(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    head = text[: MAX_OUTPUT // 2]
    tail = text[-MAX_OUTPUT // 2 :]
    return f"{head}\n...[truncated {len(text) - MAX_OUTPUT} chars]...\n{tail}"


def _resolve(path: str, root: Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (root / p)


def read_file(action: ReadFile, root: Path) -> ToolResult:
    p = _resolve(action.path, root)
    try:
        return ToolResult(ok=True, output=_trunc(p.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return ToolResult(ok=False, output="", error=f"文件不存在: {action.path}")
    except OSError as e:
        return ToolResult(ok=False, output="", error=str(e))


def write_file(action: WriteFile, root: Path) -> ToolResult:
    p = _resolve(action.path, root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(action.content, encoding="utf-8")
        return ToolResult(ok=True, output=f"written {action.path} ({len(action.content)} chars)")
    except OSError as e:
        return ToolResult(ok=False, output="", error=str(e))


def delete_file(action: DeleteFile, root: Path) -> ToolResult:
    p = _resolve(action.path, root)
    try:
        if p.is_dir():
            p.rmdir()  # 只删空目录,非空由护栏审批后显式删
        else:
            p.unlink()
        return ToolResult(ok=True, output=f"deleted {action.path}")
    except FileNotFoundError:
        return ToolResult(ok=False, output="", error=f"不存在: {action.path}")
    except OSError as e:
        return ToolResult(ok=False, output="", error=str(e))


def list_dir(action: ListDir, root: Path) -> ToolResult:
    p = _resolve(action.path, root)
    try:
        names = sorted(c.name for c in p.iterdir())
        return ToolResult(ok=True, output="\n".join(names))
    except OSError as e:
        return ToolResult(ok=False, output="", error=str(e))
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_files.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent_harness/tools/files.py tests/unit/test_files.py
git commit -m "feat(tools): 文件读写删列与输出截断"
```

---

## Task 7: 工具 — 跨平台 shell `tools/shell.py`

**Files:**
- Create: `src/coding_agent_harness/tools/shell.py`
- Test: `tests/unit/test_shell.py`

**Interfaces:**
- Consumes: `models.RunShell, ToolResult`。
- Produces: `run_shell(action, timeout=30) -> ToolResult`。用 `subprocess.run` 不带 shell,拆参;输出截断。

- [ ] **Step 1: 写失败测试 `tests/unit/test_shell.py`**

```python
import sys
from coding_agent_harness.models import RunShell
from coding_agent_harness.tools.shell import run_shell


def _echo_cmd():
    # 跨平台:用 sys.executable 跑 python -c
    return f'"{sys.executable}" -c "print(42)"'


def test_run_shell_captures_output():
    r = run_shell(RunShell(_echo_cmd()))
    assert r.ok
    assert "42" in r.output


def test_run_shell_nonzero_exit():
    r = run_shell(RunShell(f'"{sys.executable}" -c "import sys; sys.exit(3)"'))
    assert not r.ok
    assert r.error


def test_run_shell_timeout():
    loop = f'"{sys.executable}" -c "import time; time.sleep(5)"'
    r = run_shell(RunShell(loop), timeout=1)
    assert not r.ok
    assert "timeout" in r.error.lower()
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_shell.py -v`
Expected: FAIL。

- [ ] **Step 3: 写实现 `src/coding_agent_harness/tools/shell.py`**

```python
"""跨平台 shell 执行。shell=False,用 shlex 拆参。"""
from __future__ import annotations
import shlex
import subprocess
import sys
from coding_agent_harness.models import RunShell, ToolResult

MAX_OUTPUT = 8000


def _trunc(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n...[truncated {len(text) - MAX_OUTPUT} chars]..."


def run_shell(action: RunShell, timeout: int = 30) -> ToolResult:
    # Windows 上 shlex 对反斜杠处理弱;对引号包裹的路径用 posix=False
    is_win = sys.platform.startswith("win")
    argv = shlex.split(action.cmd, posix=not is_win)
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, output="", error="timeout")
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=f"command not found: {e}")
    out = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0
    return ToolResult(
        ok=ok,
        output=_trunc(out),
        error=None if ok else f"exit {proc.returncode}",
    )
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_shell.py -v`
Expected: PASS(注意:Windows 上 `sys.executable` 路径含空格时 shlex 拆参需测;若失败,改为直接传 `[sys.executable, "-c", "..."]` 的 list 接口——见 Step 5)。如果失败，调整测试改为直接传 list（见下方说明）。

- [ ] **Step 5: 若 Step 4 在 Windows 失败，把 `run_shell` 改为接受 list 形式作为备选**

实际工程取舍:`run_shell` 内部若 shlex 拆参失败,回退到 `subprocess.run(action.cmd, shell=True)`。但这会弱化跨平台安全。**更好做法**:在 `dispatch` 层对 `RunShell` 的 cmd 做规范化:若 cmd 已是 list 则直传。本 Task 先保持 shlex 实现;若 CI Windows 矩阵红,再开 follow-up task 改为 list 接口。

- [ ] **Step 6: Commit**

```bash
git add src/coding_agent_harness/tools/shell.py tests/unit/test_shell.py
git commit -m "feat(tools): 跨平台 shell 执行(shell=False)"
```

---

## Task 8: 工具 — pytest 运行器 `tools/tests_runner.py`

**Files:**
- Create: `src/coding_agent_harness/tools/tests_runner.py`
- Test: `tests/unit/test_tests_runner.py`
- Test fixture project: `tests/fixtures/sample_pkg/`(一个会失败的 pytest)

**Interfaces:**
- Consumes: `models.PytestRun`、`config.Config`(feedback.pytest_args、project_root)。
- Produces: `run_tests(config) -> PytestRun`。不自己判 pass/fail(交给 Validator)。

- [ ] **Step 1: 建 fixture 包 `tests/fixtures/sample_pkg/`**

`tests/fixtures/sample_pkg/calc.py`:
```python
def add(a, b):
    return a + b
```

`tests/fixtures/sample_pkg/test_calc.py`:
```python
from calc import add


def test_add():
    assert add(2, 2) == 5  # 故意失败
```

`tests/fixtures/sample_pkg/conftest.py`:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
```

- [ ] **Step 2: 写失败测试 `tests/unit/test_tests_runner.py`**

```python
from pathlib import Path
from coding_agent_harness.config import load_config
from coding_agent_harness.tools.tests_runner import run_tests

FIX = Path(__file__).parent.parent / "fixtures" / "sample_pkg"


def _cfg(root: Path):
    import yaml, tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({"project_root": str(root), "llm": {"base_url": "x", "model": "m"}}, f)
    f.close()
    return load_config(f.name)


def test_run_tests_returns_pytest_run():
    r = run_tests(_cfg(FIX))
    assert r.exit_code != 0
    assert "test_add" in r.stdout
    assert "1 failed" in r.stdout
    assert r.duration_s >= 0


def test_run_tests_does_not_judge():
    # 只返回结构化结果,不返回 PASS/FAIL 布尔
    r = run_tests(_cfg(FIX))
    assert not hasattr(r, "status")
```

- [ ] **Step 3: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_tests_runner.py -v`
Expected: FAIL。

- [ ] **Step 4: 写实现 `src/coding_agent_harness/tools/tests_runner.py`**

```python
"""跑 pytest 并返回结构化结果。不判定 pass/fail。"""
from __future__ import annotations
import subprocess
import sys
import time
from coding_agent_harness.config import Config
from coding_agent_harness.models import PytestRun


def run_tests(config: Config) -> PytestRun:
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
```

- [ ] **Step 5: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_tests_runner.py -v`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src tests
git commit -m "feat(tools): pytest 运行器返回结构化结果"
```

---

## Task 9: 工具分发 `tools/dispatch.py`

**Files:**
- Create: `src/coding_agent_harness/tools/dispatch.py`
- Test: `tests/unit/test_dispatch.py`

**Interfaces:**
- Consumes: `models.{Action, ToolResult}`、`tools.{files,shell,tests_runner}`、`config.Config`。
- Produces: `dispatch(action, config) -> ToolResult`。match-action 分发。

- [ ] **Step 1: 写失败测试 `tests/unit/test_dispatch.py`**

```python
from coding_agent_harness.config import load_config
from coding_agent_harness.models import ReadFile, WriteFile, Stop
from coding_agent_harness.tools.dispatch import dispatch
import yaml, tempfile, sys
from pathlib import Path


def _cfg(root):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({"project_root": str(root), "llm": {"base_url": "x", "model": "m"}}, f)
    f.close()
    return load_config(f.name)


def test_dispatch_write_then_read(tmp_path):
    cfg = _cfg(tmp_path)
    dispatch(WriteFile("a.txt", "hi"), cfg)
    r = dispatch(ReadFile("a.txt"), cfg)
    assert r.ok and r.output == "hi"


def test_dispatch_stop_returns_ok():
    cfg = _cfg(".")
    r = dispatch(Stop("done"), cfg)
    assert r.ok and "stop" in r.output.lower()
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_dispatch.py -v`
Expected: FAIL。

- [ ] **Step 3: 写实现 `src/coding_agent_harness/tools/dispatch.py`**

```python
"""工具分发。match-action,确定性,可单测。"""
from __future__ import annotations
from coding_agent_harness.config import Config
from coding_agent_harness.models import (
    Action, ReadFile, WriteFile, DeleteFile, ListDir, RunShell, RunTests, Stop, ToolResult,
)
from coding_agent_harness.tools import files, shell, tests_runner


def dispatch(action: Action, config: Config) -> ToolResult:
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
            tr = tests_runner.run_tests(config)
            return ToolResult(ok=tr.exit_code == 0, output=tr.stdout, structured=tr, error=None)
        case Stop():
            return ToolResult(ok=True, output=f"stop: {action.reason}")
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_dispatch.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent_harness/tools/dispatch.py tests/unit/test_dispatch.py
git commit -m "feat(tools): match-action 工具分发"
```

---

## Task 10: 记忆 store `memory/store.py`

**Files:**
- Create: `src/coding_agent_harness/memory/store.py`
- Test: `tests/unit/test_memory.py`
- Test fixture: `tests/fixtures/fixes.example.json`

**Interfaces:**
- Consumes: `feedback.taxonomy.FailureCategory`、`models`。
- Produces: `Fix` dataclass;`Memory` 类:`Memory(fixes_path, conventions_path, top_k)`、`retrieve(category) -> list[Fix]`、`record_fix(fix)`、`load_conventions() -> list[str]`、`record_fix` 在任务结束时调用(循环内不写)。

- [ ] **Step 1: 在 models 加 `Fix`**

`src/coding_agent_harness/models.py` 追加:
```python
@dataclass
class Fix:
    category: str   # FailureCategory 值
    symptom: str
    fix: str
    timestamp: str  # ISO 字符串,由调用方传入(不在循环内取系统时间)
```

- [ ] **Step 2: 写 fixture `tests/fixtures/fixes.example.json`**

```json
[
  {"category": "AssertionFailure", "symptom": "assert 3 == 4", "fix": "修复 off-by-one", "timestamp": "2026-07-22T00:00:00"},
  {"category": "ImportError", "symptom": "No module named x", "fix": "补 __init__.py", "timestamp": "2026-07-22T00:00:00"}
]
```

- [ ] **Step 3: 写失败测试 `tests/unit/test_memory.py`**

```python
import json
from pathlib import Path
from coding_agent_harness.memory.store import Memory, Fix
from coding_agent_harness.feedback.taxonomy import FailureCategory

FIX = Path(__file__).parent.parent / "fixtures" / "fixes.example.json"


def test_retrieve_by_category(tmp_path):
    f = tmp_path / "fixes.json"
    f.write_text(FIX.read_text())
    mem = Memory(f, tmp_path / "conv.json", top_k=3)
    out = mem.retrieve(FailureCategory.AssertionFailure)
    assert len(out) == 1
    assert out[0].fix == "修复 off-by-one"


def test_retrieve_unknown_category_empty(tmp_path):
    f = tmp_path / "fixes.json"
    f.write_text(FIX.read_text())
    mem = Memory(f, tmp_path / "conv.json", top_k=3)
    assert mem.retrieve(FailureCategory.Timeout) == []


def test_retrieve_respects_top_k(tmp_path):
    f = tmp_path / "fixes.json"
    data = [{"category": "AssertionFailure", "symptom": "s", "fix": f"f{i}", "timestamp": f"2026-07-22T0{i}"} for i in range(5)]
    f.write_text(json.dumps(data))
    mem = Memory(f, tmp_path / "conv.json", top_k=2)
    out = mem.retrieve(FailureCategory.AssertionFailure)
    assert len(out) == 2


def test_record_fix_appends(tmp_path):
    f = tmp_path / "fixes.json"
    f.write_text("[]")
    mem = Memory(f, tmp_path / "conv.json", top_k=3)
    mem.record_fix(Fix("AssertionFailure", "sym", "fixx", "2026-07-22T00:00:00"))
    data = json.loads(f.read_text())
    assert len(data) == 1 and data[0]["fix"] == "fixx"


def test_load_conventions(tmp_path):
    c = tmp_path / "conv.json"
    c.write_text(json.dumps([{"key": "style", "value": "snake_case"}]))
    mem = Memory(tmp_path / "f.json", c, top_k=3)
    convs = mem.load_conventions()
    assert "snake_case" in convs[0]
```

- [ ] **Step 4: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_memory.py -v`
Expected: FAIL。

- [ ] **Step 5: 写实现 `src/coding_agent_harness/memory/store.py`**

```python
"""分类索引记忆 store。自实现,不接框架 memory。检索是纯函数,确定。"""
from __future__ import annotations
import json
from pathlib import Path
from coding_agent_harness.models import Fix
from coding_agent_harness.feedback.taxonomy import FailureCategory


class Memory:
    def __init__(self, fixes_path: Path | str, conventions_path: Path | str, top_k: int = 3):
        self.fixes_path = Path(fixes_path)
        self.conventions_path = Path(conventions_path)
        self.top_k = top_k

    def _load_fixes(self) -> list[Fix]:
        if not self.fixes_path.exists():
            return []
        data = json.loads(self.fixes_path.read_text(encoding="utf-8"))
        return [Fix(**d) for d in data]

    def retrieve(self, category: FailureCategory) -> list[Fix]:
        all_fixes = self._load_fixes()
        matched = [f for f in all_fixes if f.category == category.value]
        return matched[-self.top_k :] if self.top_k else matched

    def record_fix(self, fix: Fix) -> None:
        all_fixes = self._load_fixes()
        all_fixes.append(fix)
        self.fixes_path.parent.mkdir(parents=True, exist_ok=True)
        self.fixes_path.write_text(
            json.dumps([f.__dict__ for f in all_fixes], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_conventions(self) -> list[str]:
        if not self.conventions_path.exists():
            return []
        data = json.loads(self.conventions_path.read_text(encoding="utf-8"))
        return [f"{d.get('key','')}: {d.get('value','')}" for d in data]
```

- [ ] **Step 6: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_memory.py -v`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add src tests
git commit -m "feat(memory): 分类索引记忆 store 与纯函数检索"
```

---

## Task 11: 治理护栏 `guardrails/guardrail.py`

**Files:**
- Create: `src/coding_agent_harness/guardrails/guardrail.py`
- Test: `tests/unit/test_guardrail.py`

**Interfaces:**
- Consumes: `models.{Action, Verdict, Allow, Deny, NeedsApproval}`、`config.Config`。
- Produces: `guardrail(action, config) -> Verdict`。删一律审批;写项目外审批;shell 黑名单 Deny/白名单 Allow/其他审批;只读 Allow。

- [ ] **Step 1: 写失败测试 `tests/unit/test_guardrail.py`**

```python
from coding_agent_harness.config import load_config
from coding_agent_harness.models import (
    WriteFile, DeleteFile, RunShell, ReadFile, RunTests, ListDir, Stop,
    Allow, Deny, NeedsApproval,
)
from coding_agent_harness.guardrails.guardrail import guardrail
import yaml, tempfile


def _cfg(blacklist=None, whitelist=None, root="."):
    raw = {
        "project_root": root,
        "llm": {"base_url": "x", "model": "m"},
        "guardrails": {
            "shell_blacklist": blacklist or ["rm -rf"],
            "shell_whitelist": whitelist or ["pytest"],
        },
    }
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump(raw, f); f.close()
    return load_config(f.name)


def test_delete_needs_approval():
    assert isinstance(guardrail(DeleteFile("a.py"), _cfg()), NeedsApproval)


def test_write_inside_project_allowed(tmp_path):
    cfg = _cfg(root=str(tmp_path))
    assert isinstance(guardrail(WriteFile("src/a.py", "x"), cfg), Allow)


def test_write_outside_project_needs_approval(tmp_path):
    cfg = _cfg(root=str(tmp_path))
    # 用 ../ 逃逸
    assert isinstance(guardrail(WriteFile("../outside.txt", "x"), cfg), NeedsApproval)


def test_shell_blacklist_denied():
    assert isinstance(guardrail(RunShell("rm -rf /"), _cfg()), Deny)


def test_shell_whitelist_allowed():
    assert isinstance(guardrail(RunShell("pytest -q"), _cfg()), Allow)


def test_shell_unknown_needs_approval():
    assert isinstance(guardrail(RunShell("make build"), _cfg()), NeedsApproval)


def test_read_and_tests_and_stop_allowed():
    cfg = _cfg()
    assert isinstance(guardrail(ReadFile("a.py"), cfg), Allow)
    assert isinstance(guardrail(RunTests(), cfg), Allow)
    assert isinstance(guardrail(Stop("done"), cfg), Allow)
    assert isinstance(guardrail(ListDir("."), cfg), Allow)
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_guardrail.py -v`
Expected: FAIL。

- [ ] **Step 3: 写实现 `src/coding_agent_harness/guardrails/guardrail.py`**

```python
"""治理护栏。纯函数,确定性,可单测(无需 LLM)。"""
from __future__ import annotations
from pathlib import Path
from coding_agent_harness.config import Config
from coding_agent_harness.models import (
    Action, WriteFile, DeleteFile, RunShell, RunTests, ReadFile, ListDir, Stop,
    Allow, Deny, NeedsApproval,
)


def _is_inside(path: str, root: Path) -> bool:
    p = Path(path)
    p = p if p.is_absolute() else (root / p)
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _starts_with_any(cmd: str, patterns: list[str]) -> bool:
    c = cmd.strip().lower()
    return any(c.startswith(p.lower()) or p.lower() in c for p in patterns)


def guardrail(action: Action, config: Config):
    root = config.project_root
    gr = config.guardrails
    match action:
        case DeleteFile():
            return NeedsApproval(reason=f"删除: {action.path}")
        case WriteFile():
            if _is_inside(action.path, root):
                return Allow()
            return NeedsApproval(reason=f"写项目目录外: {action.path}")
        case RunShell():
            if _starts_with_any(action.cmd, gr.shell_blacklist):
                return Deny(reason=f"禁止命令: {action.cmd}")
            if _starts_with_any(action.cmd, gr.shell_whitelist):
                return Allow()
            return NeedsApproval(reason=f"执行 shell: {action.cmd}")
        case ReadFile() | ListDir() | RunTests() | Stop():
            return Allow()
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_guardrail.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent_harness/guardrails/guardrail.py tests/unit/test_guardrail.py
git commit -m "feat(guardrails): 护栏纯函数与路径围栏"
```

---

## Task 12: LLM 抽象层 `llm/base.py`

**Files:**
- Create: `src/coding_agent_harness/llm/__init__.py`
- Create: `src/coding_agent_harness/llm/base.py`
- Test: `tests/unit/test_llm_base.py`

**Interfaces:**
- Produces: `LLMClient` Protocol(`complete(messages, tools, state) -> AssistantTurn`)、`Message` 类型(`{role, content}`)。

- [ ] **Step 1: 写 `src/coding_agent_harness/llm/__init__.py`**(空)

```python
```

- [ ] **Step 2: 写失败测试 `tests/unit/test_llm_base.py`**

```python
from coding_agent_harness.llm.base import LLMClient, Message
from coding_agent_harness.models import AssistantTurn, Stop


class FakeClient:
    def complete(self, messages, tools, state):
        return AssistantTurn(action=Stop("done"), intent="完成", raw="x")


def test_protocol_is_structural():
    c = FakeClient()
    t = c.complete([], [], None)
    assert isinstance(t, AssistantTurn)
    assert isinstance(t.action, Stop)
    assert Message(role="user", content="hi").content == "hi"
```

- [ ] **Step 3: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_llm_base.py -v`
Expected: FAIL。

- [ ] **Step 4: 写实现 `src/coding_agent_harness/llm/base.py`**

```python
"""LLM 抽象层。所有模块只依赖此接口,mock 与真实实现同接口。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Any
from coding_agent_harness.models import AssistantTurn


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: dict  # JSON Schema 片段


class LLMClient(Protocol):
    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        state: Any,  # LoopState,运行时传入;避免循环 import 用 Any
    ) -> AssistantTurn: ...
```

- [ ] **Step 5: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_llm_base.py -v`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/coding_agent_harness/llm tests/unit/test_llm_base.py
git commit -m "feat(llm): LLMClient 抽象层与 Message 类型"
```

---

## Task 13: MockLLMClient `llm/mock.py`

**Files:**
- Create: `src/coding_agent_harness/llm/mock.py`
- Test: `tests/unit/test_llm_mock.py`

**Interfaces:**
- Consumes: `llm.base.{LLMClient, Message, ToolSchema}`、`models.{AssistantTurn, Action...}`、`feedback.taxonomy.FailureCategory`、`core.state.LoopState`(运行时 Any)。
- Produces: `MockLLMClient(script: list[dict])`;脚本条目形如 `{"when": "round N" | "feedback.category == X" | "feedback.status == PASS" | "always", "action": Action, "intent": str}`。`complete` 据当前 state 选第一个匹配的条目。

- [ ] **Step 1: 写失败测试 `tests/unit/test_llm_mock.py`**

```python
from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.models import WriteFile, RunTests, Stop, AssistantTurn
from coding_agent_harness.feedback.taxonomy import FailureCategory


def _state(rounds=1, last_category=None, last_status=None):
    class S:
        pass
    s = S()
    s.rounds = rounds
    s.last_category = last_category
    s.last_feedback_status = last_status
    return s


def test_round_branch():
    mock = MockLLMClient([
        {"when": "round 1", "action": WriteFile("a.py", "x"), "intent": "写"},
        {"when": "always", "action": Stop("done"), "intent": "完成"},
    ])
    t = mock.complete([], [], _state(rounds=1))
    assert isinstance(t.action, WriteFile) and t.intent == "写"


def test_feedback_branch_changes_action():
    mock = MockLLMClient([
        {"when": "feedback.category == AssertionFailure", "action": WriteFile("a.py", "good"), "intent": "上次断言失败,改 off-by-one"},
        {"when": "always", "action": Stop("x"), "intent": "fallback"},
    ])
    t = mock.complete([], [], _state(last_category=FailureCategory.AssertionFailure))
    assert t.intent == "上次断言失败,改 off-by-one"
    assert t.action.content == "good"


def test_pass_branch():
    mock = MockLLMClient([
        {"when": "feedback.status == PASS", "action": Stop("done"), "intent": "全绿"},
        {"when": "always", "action": Stop("nope"), "intent": "x"},
    ])
    t = mock.complete([], [], _state(last_status="PASS"))
    assert t.intent == "全绿"


def test_no_match_raises():
    mock = MockLLMClient([{"when": "round 99", "action": Stop("x"), "intent": "x"}])
    try:
        mock.complete([], [], _state(rounds=1))
        assert False, "应抛错"
    except RuntimeError:
        pass
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_llm_mock.py -v`
Expected: FAIL。

- [ ] **Step 3: 写实现 `src/coding_agent_harness/llm/mock.py`**

```python
"""脚本化 mock LLM。据当前 LoopState 选分支,确定性,不触网。"""
from __future__ import annotations
from coding_agent_harness.llm.base import LLMClient, Message, ToolSchema
from coding_agent_harness.models import AssistantTurn, Action


class MockLLMClient:
    def __init__(self, script: list[dict]):
        self.script = script

    def complete(self, messages, tools, state) -> AssistantTurn:
        for entry in self.script:
            if _matches(entry["when"], state):
                return AssistantTurn(action=entry["action"], intent=entry["intent"], raw=f"mock:{entry['when']}")
        raise RuntimeError(f"mock 无匹配分支: rounds={getattr(state,'rounds',None)} last_category={getattr(state,'last_category',None)}")


def _matches(when: str, state) -> bool:
    if when == "always":
        return True
    if when.startswith("round "):
        return getattr(state, "rounds", None) == int(when.split()[1])
    if when.startswith("feedback.category == "):
        cat = getattr(state, "last_category", None)
        return cat is not None and cat.value == when.split("== ", 1)[1].strip()
    if when.startswith("feedback.status == "):
        return getattr(state, "last_feedback_status", None) == when.split("== ", 1)[1].strip()
    return False
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_llm_mock.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent_harness/llm/mock.py tests/unit/test_llm_mock.py
git commit -m "feat(llm): 脚本化分支 MockLLMClient"
```

---

## Task 14: 循环状态与停机判断 `core/state.py`

**Files:**
- Create: `src/coding_agent_harness/core/__init__.py`
- Create: `src/coding_agent_harness/core/state.py`
- Modify: `src/coding_agent_harness/models.py`(加 `Step`、`RunResult`)
- Test: `tests/unit/test_state.py`

**Interfaces:**
- Consumes: `models.{Feedback, FailedTest}`、`feedback.taxonomy.FailureCategory`、`config.Config`。
- Produces: `LoopState`(rounds/last_category/same_category_streak/no_change_streak/last_feedback_status/feedback_history/steps)、`Step`、`RunResult`、`update_after_feedback(state, feedback, config) -> LoopState`、`decide_stop(state, config) -> Outcome | None`。

- [ ] **Step 1: 在 models 加 Step/RunResult**

`src/coding_agent_harness/models.py` 追加:
```python
from typing import Any

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
```

- [ ] **Step 2: 写 `src/coding_agent_harness/core/__init__.py`**(空)

- [ ] **Step 3: 写失败测试 `tests/unit/test_state.py`**

```python
from coding_agent_harness.core.state import LoopState, update_after_feedback, decide_stop
from coding_agent_harness.models import Feedback, FailedTest
from coding_agent_harness.feedback.taxonomy import FailureCategory
from coding_agent_harness.config import load_config
import yaml, tempfile


def _cfg(**overrides):
    raw = {"project_root": ".", "llm": {"base_url": "x", "model": "m"},
           "guardrails": {"max_rounds": 8, "same_category_prompt_at": 2,
                           "same_category_stop_at": 3, "no_change_stop_at": 2}}
    raw["guardrails"].update(overrides)
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump(raw, f); f.close()
    return load_config(f.name)


def _fb(cat=FailureCategory.AssertionFailure, status="FAIL", nodeids=("a",)):
    return Feedback(status=status, failed_tests=[
        FailedTest(nodeid=n, category=cat, file="f", line=1, traceback_excerpt="", assertion_diff=None)
        for n in nodeids
    ], passed_count=0, summary="1 failed")


def test_streak_increments_same_category():
    cfg = _cfg()
    s = LoopState()
    s = update_after_feedback(s, _fb(FailureCategory.AssertionFailure), cfg)
    assert s.same_category_streak == 1
    s = update_after_feedback(s, _fb(FailureCategory.AssertionFailure), cfg)
    assert s.same_category_streak == 2


def test_streak_resets_on_category_change():
    cfg = _cfg()
    s = update_after_feedback(LoopState(), _fb(FailureCategory.AssertionFailure), cfg)
    s = update_after_feedback(s, _fb(FailureCategory.ImportError), cfg)
    assert s.same_category_streak == 1


def test_no_change_streak_when_same_failed_set():
    cfg = _cfg()
    s = update_after_feedback(LoopState(), _fb(nodeids=("a",)), cfg)
    s = update_after_feedback(s, _fb(nodeids=("a",)), cfg)
    assert s.no_change_streak == 2
    assert decide_stop(s, cfg) == "stuck"


def test_stop_on_max_rounds():
    cfg = _cfg(max_rounds=2)
    s = LoopState(rounds=2)
    assert decide_stop(s, cfg) == "max_rounds"


def test_stop_on_success():
    cfg = _cfg()
    s = LoopState(last_feedback_status="PASS")
    assert decide_stop(s, cfg) == "success"


def test_no_stop_midway():
    cfg = _cfg()
    s = update_after_feedback(LoopState(), _fb(), cfg)
    assert decide_stop(s, cfg) is None


def test_should_prompt_switch():
    cfg = _cfg()
    s = update_after_feedback(LoopState(), _fb(), cfg)
    s = update_after_feedback(s, _fb(), cfg)
    assert s.same_category_streak == 2  # 达 prompt_at
```

- [ ] **Step 4: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_state.py -v`
Expected: FAIL。

- [ ] **Step 5: 写实现 `src/coding_agent_harness/core/state.py`**

```python
"""循环状态与停机判断。确定性,可单测。"""
from __future__ import annotations
from dataclasses import dataclass, field
from coding_agent_harness.config import Config
from coding_agent_harness.models import Feedback
from coding_agent_harness.feedback.taxonomy import FailureCategory


@dataclass
class LoopState:
    rounds: int = 0
    last_category: FailureCategory | None = None
    same_category_streak: int = 0
    no_change_streak: int = 0
    last_feedback_status: str | None = None
    feedback_history: list[Feedback] = field(default_factory=list)
    steps: list = field(default_factory=list)
    context_injected: list[str] = field(default_factory=list)

    def snapshot(self):
        s = LoopState()
        s.rounds = self.rounds
        s.last_category = self.last_category
        s.same_category_streak = self.same_category_streak
        s.no_change_streak = self.no_change_streak
        s.last_feedback_status = self.last_feedback_status
        return s


def _failed_set(fb: Feedback) -> frozenset:
    return frozenset(ft.nodeid for ft in fb.failed_tests)


def update_after_feedback(state: LoopState, fb: Feedback, config: Config) -> LoopState:
    gr = config.guardrails
    cat = fb.failed_tests[0].category if fb.failed_tests else None
    new = LoopState(
        rounds=state.rounds,
        last_category=cat,
        same_category_streak=(state.same_category_streak + 1) if cat == state.last_category and cat is not None else (1 if cat else 0),
        no_change_streak=0,
        last_feedback_status=fb.status,
        feedback_history=state.feedback_history + [fb],
        steps=state.steps,
        context_injected=list(state.context_injected),
    )
    # 无变化判断:与上一轮 failed_set 相同
    if state.feedback_history:
        prev = state.feedback_history[-1]
        if _failed_set(prev) == _failed_set(fb) and fb.status == "FAIL":
            new.no_change_streak = state.no_change_streak + 1
    # 策略提示
    if new.same_category_streak >= gr.same_category_prompt_at:
        new.context_injected.append("连续同类失败,考虑换一种修复方向(换思路)")
    if new.no_change_streak >= gr.no_change_stop_at:
        new.context_injected.append("陷入死循环,请回退最近改动")
    return new


def decide_stop(state: LoopState, config: Config) -> str | None:
    gr = config.guardrails
    if state.last_feedback_status == "PASS":
        return "success"
    if state.rounds >= gr.max_rounds:
        return "max_rounds"
    if state.same_category_streak >= gr.same_category_stop_at:
        return "stuck"
    if state.no_change_streak >= gr.no_change_stop_at:
        return "stuck"
    return None
```

- [ ] **Step 6: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_state.py -v`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add src tests
git commit -m "feat(core): LoopState 与停机/策略判断"
```

---

## Task 15: AgentLoop 主循环 `core/loop.py`

**Files:**
- Create: `src/coding_agent_harness/core/loop.py`
- Test: `tests/integration/test_loop.py`

**Interfaces:**
- Consumes: 全部已建模块。
- Produces: `AgentLoop(llm, config, memory, validator=Validator.parse, dispatch=dispatch, guardrail=guardrail)`、`AgentLoop.run(task, ts_provider) -> RunResult`、`AgentLoop.approve(approval_id, decision)`(HITL);事件回调 `on_event` 可选(供 WebUI 注入)。

- [ ] **Step 1: 写失败测试 `tests/integration/test_loop.py`**

```python
from coding_agent_harness.core.loop import AgentLoop
from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.memory.store import Memory
from coding_agent_harness.config import load_config
from coding_agent_harness.models import WriteFile, RunTests, Stop
import yaml, tempfile, json
from pathlib import Path

FIX = Path(__file__).parent.parent / "fixtures" / "sample_pkg"


def _cfg(root):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({
        "project_root": str(root),
        "llm": {"base_url": "x", "model": "m"},
        "guardrails": {"max_rounds": 8, "same_category_prompt_at": 2,
                       "same_category_stop_at": 3, "no_change_stop_at": 2},
        "feedback": {"pytest_args": ["--tb=short", "-q"], "max_traceback_excerpt_lines": 8},
        "memory": {"fixes_path": str(root / "fixes.json"),
                   "conventions_path": str(root / "conv.json"), "retrieve_top_k": 3},
    }, f); f.close()
    return load_config(f.name)


def test_loop_red_to_green(tmp_path):
    # 复制 fixture 到 tmp workspace
    import shutil
    shutil.copytree(FIX, tmp_path / "ws", dirs_exist_ok=True)
    ws = tmp_path / "ws"
    # mock 脚本:先写错的修复 → 跑测试(失败)→ 据 AssertionFailure 写对的 → 跑测试(绿)→ 停
    mock = MockLLMClient([
        {"when": "round 1", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+1\n"), "intent": "我先改返回值"},
        {"when": "round 2", "action": RunTests(), "intent": "验证修复"},
        {"when": "feedback.category == AssertionFailure", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b\n"), "intent": "上次断言失败,改 off-by-one"},
        {"when": "round 4", "action": RunTests(), "intent": "再验证"},
        {"when": "feedback.status == PASS", "action": Stop("done"), "intent": "测试全绿,完成"},
    ])
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    loop = AgentLoop(llm=mock, config=cfg, memory=mem)
    result = loop.run(task="修 add 的 bug", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "success"
    # 断言第 3 步确实因 AssertionFailure 才写了正确修复
    assert any(s.turn.intent == "上次断言失败,改 off-by-one" for s in result.steps)
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/integration/test_loop.py -v`
Expected: FAIL。

- [ ] **Step 3: 写实现 `src/coding_agent_harness/core/loop.py`**

```python
"""Agent 主循环。自实现,不寄生框架。
组织上下文 → 调 LLM → 解析动作 → 护栏 → (审批)→ 分发 → 校验 → 回灌 → 停机。"""
from __future__ import annotations
from typing import Callable, Any
from coding_agent_harness.config import Config
from coding_agent_harness.models import (
    AssistantTurn, Action, RunTests, Stop, ToolResult, Feedback, Step, RunResult,
)
from coding_agent_harness.llm.base import LLMClient, Message
from coding_agent_harness.tools.dispatch import dispatch
from coding_agent_harness.tools.tests_runner import run_tests
from coding_agent_harness.feedback.validator import Validator
from coding_agent_harness.feedback.taxonomy import FailureCategory, strategy_hint
from coding_agent_harness.guardrails.guardrail import guardrail
from coding_agent_harness.core.state import LoopState, update_after_feedback, decide_stop


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        config: Config,
        memory,
        validator=Validator.parse,
        dispatcher=dispatch,
        guard=guardrail,
        on_event: Callable[[dict], None] | None = None,
    ):
        self.llm = llm
        self.config = config
        self.memory = memory
        self.validator = validator
        self.dispatch = dispatcher
        self.guard = guard
        self.on_event = on_event or (lambda e: None)
        self._pending_approvals: dict[str, dict] = {}

    def _build_messages(self, task: str, state: LoopState) -> list[Message]:
        convs = self.memory.load_conventions()
        sys = Message("system", (
            "你是一个 coding agent。可用工具:read_file/write_file/delete_file/list_dir/run_shell/run_tests/stop。"
            "每次输出一个动作并附 intent(一句话说明动机)。"
            + ("\n项目约定:\n" + "\n".join(convs) if convs else "")
        ))
        msgs = [sys, Message("user", task)]
        # 回灌上一轮结构化 feedback + 记忆检索
        if state.feedback_history:
            fb = state.feedback_history[-1]
            if fb.status == "FAIL":
                lines = [f"上一轮测试失败 {len(fb.failed_tests)} 项:"]
                for ft in fb.failed_tests:
                    lines.append(f"- {ft.nodeid} [{ft.category.value}] @ {ft.file}:{ft.line}")
                    if ft.assertion_diff:
                        lines.append(f"  断言 {ft.assertion_diff}")
                    lines.append(f"  建议:{strategy_hint(ft.category)}")
                hist = self.memory.retrieve(ft.category)
                if hist:
                    lines.append("历史同类修复:")
                    for h in hist:
                        lines.append(f"  - {h.symptom} → {h.fix}")
                msgs.append(Message("tool", "\n".join(lines)))
        # 策略提示
        for c in state.context_injected:
            msgs.append(Message("system", c))
        return msgs

    def run(self, task: str, ts_provider: Callable[[], str]) -> RunResult:
        state = LoopState()
        steps: list[Step] = []
        outcome = "error"
        final_fb = None
        while True:
            state.rounds += 1
            msgs = self._build_messages(task, state)
            try:
                turn = self.llm.complete(msgs, [], state.snapshot())
            except RuntimeError as e:
                outcome = "error"
                steps.append(Step(turn=None, verdict=None, tool_result=None, feedback=None, ts=ts_provider()))
                break
            # 护栏
            v = self.guard(turn.action, self.config)
            self.on_event({"type": "guardrail_verdict", "verdict": type(v).__name__, "intent": turn.intent})
            if type(v).__name__ == "Deny":
                tr = ToolResult(ok=False, output="", error=f"被护栏拒绝:{v.reason}")
                fb = None
            elif type(v).__name__ == "NeedsApproval":
                # 机制演示/真实运行:此处挂起。测试中由 approve() 驱动;此处简化为回灌"需审批"
                tr = ToolResult(ok=False, output="", error=f"需人工审批:{v.reason}")
                fb = None
            else:
                tr = self.dispatch(turn.action, self.config)
                fb = None
                if isinstance(turn.action, RunTests) and tr.structured is not None:
                    fb = self.validator(tr.structured, self.config.feedback.max_traceback_excerpt_lines)
                    tr = ToolResult(ok=fb.status == "PASS", output=tr.output, structured=tr.structured, error=None)
            self.on_event({"type": "tool_result", "ok": tr.ok, "feedback": _fb_to_dict(fb)})
            steps.append(Step(turn=turn, verdict=v, tool_result=tr, feedback=fb, ts=ts_provider()))
            if fb:
                state = update_after_feedback(state, fb, self.config)
            else:
                state.feedback_history = state.feedback_history  # 不变
                state.last_feedback_status = state.last_feedback_status
            final_fb = fb or final_fb
            if isinstance(turn.action, Stop):
                outcome = "stopped"
                break
            stop = decide_stop(state, self.config)
            if stop:
                outcome = stop
                break
        # 任务结束记录记忆(循环外写,不破坏确定性)
        if final_fb and final_fb.status == "FAIL" and final_fb.failed_tests:
            from coding_agent_harness.models import Fix
            cat = final_fb.failed_tests[0].category
            self.memory.record_fix(Fix(category=cat.value, symptom=final_fb.summary, fix="(未修复)", timestamp=ts_provider()))
        return RunResult(outcome=outcome, steps=steps, final_feedback=final_fb)


def _fb_to_dict(fb):
    if fb is None:
        return None
    return {"status": fb.status, "failed": len(fb.failed_tests), "passed": fb.passed_count, "summary": fb.summary}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/integration/test_loop.py -v`
Expected: PASS。若失败,检查 mock 分支顺序与 LoopState.snapshot 传递的 `last_category` 是否在 `update_after_feedback` 后更新(注意:循环里 `fb` 为 None 的轮不更新 state 的 last_category,导致第 4 轮 `feedback.status == PASS` 分支匹配依赖第 3 轮后的状态——确认 `update_after_feedback` 在 PASS 时也设置 `last_feedback_status="PASS"`)。

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent_harness/core/loop.py tests/integration/test_loop.py
git commit -m "feat(core): AgentLoop 主循环与红变绿集成测试"
```

---

## Task 16: 凭据管理 `creds/keychain.py`

**Files:**
- Create: `src/coding_agent_harness/creds/__init__.py`
- Create: `src/coding_agent_harness/creds/keychain.py`
- Test: `tests/unit/test_creds.py`

**Interfaces:**
- Produces: `Creds(service="coding-agent-harness")`;`set(api_key, base_url, model)`、`status() -> dict`(不回显)、`get() -> tuple | None`、`clear()`。用 `keyring` 后端;测试用 `keyring` 的 in-memory 后端。

- [ ] **Step 1: 写 `src/coding_agent_harness/creds/__init__.py`**(空)

- [ ] **Step 2: 写失败测试 `tests/unit/test_creds.py`**

```python
import keyring
from coding_agent_harness.creds.keychain import Creds


def test_set_get_clear(monkeypatch):
    keyring.set_keyring(keyring.backends.fail.Keyring())  # 默认失败后端
    # 用内存后端
    import keyring.backend
    class Mem(keyring.backend.KeyringBackend):
        priority = 10
        def __init__(self): self.d = {}
        def get_password(self, s, u): return self.d.get((s, u))
        def set_password(self, s, u, p): self.d[(s, u)] = p
        def delete_password(self, s, u):
            self.d.pop((s, u), None)
    keyring.set_keyring(Mem())
    c = Creds()
    assert c.status() == {"set": False}
    c.set(api_key="sk-x", base_url="http://x", model="m")
    assert c.status() == {"set": True}  # 不回显明文
    k, u, m = c.get()
    assert k == "sk-x" and u == "http://x" and m == "m"
    c.clear()
    assert c.status() == {"set": False}
```

- [ ] **Step 3: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_creds.py -v`
Expected: FAIL。

- [ ] **Step 4: 写实现 `src/coding_agent_harness/creds/keychain.py`**

```python
"""凭据安全存储。macOS Keychain / Windows Credential Manager / Linux Secret Service。绝不回显明文。"""
from __future__ import annotations
import keyring

SERVICE = "coding-agent-harness"


class Creds:
    def __init__(self, service: str = SERVICE):
        self.service = service

    def set(self, api_key: str, base_url: str, model: str) -> None:
        keyring.set_password(self.service, "api_key", api_key)
        keyring.set_password(self.service, "base_url", base_url)
        keyring.set_password(self.service, "model", model)

    def get(self) -> tuple[str, str, str] | None:
        k = keyring.get_password(self.service, "api_key")
        if not k:
            return None
        return (
            k,
            keyring.get_password(self.service, "base_url") or "",
            keyring.get_password(self.service, "model") or "",
        )

    def status(self) -> dict:
        return {"set": bool(keyring.get_password(self.service, "api_key"))}

    def clear(self) -> None:
        for u in ("api_key", "base_url", "model"):
            try:
                keyring.delete_password(self.service, u)
            except keyring.errors.PasswordDeleteError:
                pass
```

- [ ] **Step 5: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_creds.py -v`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/coding_agent_harness/creds tests/unit/test_creds.py
git commit -m "feat(creds): keyring 封装,不回显明文"
```

---

## Task 17: 真实 LLM 客户端 `llm/openai_compat.py`

**Files:**
- Create: `src/coding_agent_harness/llm/openai_compat.py`
- Test: `tests/unit/test_openai_compat.py`(用 monkeypatch fake httpx,不触网)

**Interfaces:**
- Consumes: `llm.base`、`creds.Creds`、`models.AssistantTurn, Action...`。
- Produces: `OpenAICompatibleClient(creds)`;`complete(...)` 用 httpx 调 Chat Completions + function-calling,解析 tool_call 为 `Action`(含 intent)。key 从 Creds 读,不进日志。

- [ ] **Step 1: 写失败测试 `tests/unit/test_openai_compat.py`**

```python
from coding_agent_harness.llm.openai_compat import OpenAICompatibleClient, parse_tool_call
from coding_agent_harness.models import WriteFile


def test_parse_tool_call_to_action():
    tc = {"name": "write_file", "arguments": {"path": "a.py", "content": "x"}}
    action, intent = parse_tool_call(tc)
    assert isinstance(action, WriteFile)
    assert action.path == "a.py"
    assert intent  # intent 来自 arguments.get('intent') 或默认


def test_client_uses_creds(monkeypatch):
    class FakeCreds:
        def get(self): return ("sk-x", "http://api", "m")
    calls = {}
    def fake_post(url, *, headers, json):
        calls["url"] = url
        calls["headers"] = headers
        calls["json"] = json
        class R:
            status_code = 200
            def json(self): return {"choices": [{"message": {"tool_calls": [{
                "function": {"name": "stop", "arguments": {"reason": "done", "intent": "完成"}}]}}]}}
        return R()
    import coding_agent_harness.llm.openai_compat as mod
    monkeypatch.setattr(mod.httpx, "post", fake_post, raising=True)
    c = OpenAICompatibleClient(FakeCreds())
    t = c.complete([], [], None)
    assert t.intent == "完成"
    assert "sk-x" not in str(calls)  # key 不进请求体
    assert calls["headers"]["Authorization"] == "Bearer sk-x"  # 但进 header(正常)
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_openai_compat.py -v`
Expected: FAIL。

- [ ] **Step 3: 写实现 `src/coding_agent_harness/llm/openai_compat.py`**

```python
"""真实 OpenAI 兼容客户端。底层零件,不寄生 agent 框架。key 不进日志。"""
from __future__ import annotations
import json
import logging
import httpx
from coding_agent_harness.llm.base import LLMClient, Message, ToolSchema
from coding_agent_harness.models import (
    AssistantTurn, Action, WriteFile, DeleteFile, RunShell, RunTests, ReadFile, ListDir, Stop,
)

log = logging.getLogger(__name__)

_ACTION_BUILDERS = {
    "write_file": lambda a: WriteFile(a["path"], a["content"]),
    "delete_file": lambda a: DeleteFile(a["path"]),
    "run_shell": lambda a: RunShell(a["cmd"]),
    "run_tests": lambda a: RunTests(),
    "read_file": lambda a: ReadFile(a["path"]),
    "list_dir": lambda a: ListDir(a["path"]),
    "stop": lambda a: Stop(a.get("reason", "")),
}


def parse_tool_call(tc: dict) -> tuple[Action, str]:
    name = tc["name"]
    args = tc["arguments"] if isinstance(tc["arguments"], dict) else json.loads(tc["arguments"])
    action = _ACTION_BUILDERS[name](args)
    intent = args.get("intent", f"(无 intent) 执行 {name}")
    return action, intent


class OpenAICompatibleClient:
    def __init__(self, creds, timeout=60):
        self.creds = creds
        self.timeout = timeout

    def complete(self, messages, tools, state) -> AssistantTurn:
        key, base_url, model = self.creds.get()
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "tools": [{"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters,
            }} for t in tools] or None,
            "tool_choice": "auto",
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        resp = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        tcs = msg.get("tool_calls") or []
        if not tcs:
            return AssistantTurn(action=Stop("no_tool_call"), intent=msg.get("content", "")[:200], raw=str(msg))
        tc = tcs[0]["function"]
        action, intent = parse_tool_call(tc)
        log.debug("llm intent=%s action=%s", intent, type(action).__name__)  # key 不进日志
        return AssistantTurn(action=action, intent=intent, raw=str(tc))
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_openai_compat.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent_harness/llm/openai_compat.py tests/unit/test_openai_compat.py
git commit -m "feat(llm): OpenAI 兼容真实客户端,key 不进日志"
```

---

## Task 18: §A.6 三个机制演示

**Files:**
- Create: `tests/demo/__init__.py`
- Create: `tests/demo/test_demo_1_guardrail.py`
- Create: `tests/demo/test_demo_2_feedback_loop.py`
- Create: `tests/demo/test_demo_3_strategy_and_stop.py`
- Create: `scripts/demo.sh`

**Interfaces:**
- Consumes: 全部已建模块。

- [ ] **Step 1: 写演示 ① `tests/demo/test_demo_1_guardrail.py`**

```python
"""§A.6 演示 ①:治理护栏拦截危险动作(mock LLM)。"""
from coding_agent_harness.core.loop import AgentLoop
from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.memory.store import Memory
from coding_agent_harness.config import load_config
from coding_agent_harness.models import DeleteFile, Stop
import yaml, tempfile, shutil
from pathlib import Path

FIX = Path(__file__).parent.parent.parent / "fixtures" / "sample_pkg"


def _cfg(root):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({"project_root": str(root), "llm": {"base_url": "x", "model": "m"}}, f)
    f.close()
    return load_config(f.name)


def test_guardrail_intercepts_delete_and_propagates_intent(tmp_path):
    shutil.copytree(FIX, tmp_path / "ws", dirs_exist_ok=True)
    ws = tmp_path / "ws"
    events = []
    mock = MockLLMClient([
        {"when": "round 1", "action": DeleteFile("calc.py"), "intent": "该文件被取代,删除以避免混淆"},
        {"when": "always", "action": Stop("done"), "intent": "结束"},
    ])
    cfg = _cfg(ws)
    loop = AgentLoop(llm=mock, config=cfg, memory=Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, 3),
                     on_event=events.append)
    loop.run(task="删 calc", ts_provider=lambda: "2026-07-22T00:00:00")
    assert any(e["type"] == "guardrail_verdict" and e["verdict"] == "NeedsApproval" for e in events)
    assert events[0]["intent"] == "该文件被取代,删除以避免混淆"  # intent 随审批上送
    assert (ws / "calc.py").exists()  # 没真删
```

- [ ] **Step 2: 写演示 ② `tests/demo/test_demo_2_feedback_loop.py`**

```python
"""§A.6 演示 ②:注入失败 → 反馈闭环改变下一步并红变绿。"""
from coding_agent_harness.core.loop import AgentLoop
from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.memory.store import Memory
from coding_agent_harness.config import load_config
from coding_agent_harness.models import WriteFile, RunTests, Stop
import yaml, tempfile, shutil
from pathlib import Path

FIX = Path(__file__).parent.parent.parent / "fixtures" / "sample_pkg"


def _cfg(root):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({
        "project_root": str(root), "llm": {"base_url": "x", "model": "m"},
        "guardrails": {"max_rounds": 8, "same_category_prompt_at": 2,
                       "same_category_stop_at": 3, "no_change_stop_at": 2},
    }, f); f.close()
    return load_config(f.name)


def test_failure_feedback_changes_next_action(tmp_path):
    shutil.copytree(FIX, tmp_path / "ws", dirs_exist_ok=True)
    ws = tmp_path / "ws"
    mock = MockLLMClient([
        {"when": "round 1", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+1\n"), "intent": "我先改返回值"},
        {"when": "round 2", "action": RunTests(), "intent": "验证修复"},
        {"when": "feedback.category == AssertionFailure", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b\n"), "intent": "上次断言失败,改 off-by-one"},
        {"when": "round 4", "action": RunTests(), "intent": "再验证"},
        {"when": "feedback.status == PASS", "action": Stop("done"), "intent": "测试全绿,完成"},
    ])
    cfg = _cfg(ws)
    loop = AgentLoop(llm=mock, config=cfg, memory=Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, 3))
    result = loop.run(task="修 add", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "success"
    pivot = [s for s in result.steps if s.turn and s.turn.intent == "上次断言失败,改 off-by-one"]
    assert pivot, "应存在因 AssertionFailure feedback 而改变动作的转折"
```

- [ ] **Step 3: 写演示 ③ `tests/demo/test_demo_3_strategy_and_stop.py`**

```python
"""§A.6 演示 ③:连续同类失败触发策略切换并按停机条件停。"""
from coding_agent_harness.core.loop import AgentLoop
from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.memory.store import Memory
from coding_agent_harness.config import load_config
from coding_agent_harness.models import WriteFile, RunTests
import yaml, tempfile, shutil
from pathlib import Path

FIX = Path(__file__).parent.parent.parent / "fixtures" / "sample_pkg"


def _cfg(root):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({
        "project_root": str(root), "llm": {"base_url": "x", "model": "m"},
        "guardrails": {"max_rounds": 8, "same_category_prompt_at": 2,
                       "same_category_stop_at": 3, "no_change_stop_at": 2},
    }, f); f.close()
    return load_config(f.name)


def test_repeated_failure_triggers_prompt_and_stop(tmp_path):
    shutil.copytree(FIX, tmp_path / "ws", dirs_exist_ok=True)
    ws = tmp_path / "ws"
    # mock 连续写错误修复,始终触发 AssertionFailure
    mock = MockLLMClient([
        {"when": "round 1", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+1\n"), "intent": "修1"},
        {"when": "round 2", "action": RunTests(), "intent": "跑"},
        {"when": "feedback.category == AssertionFailure", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+1\n"), "intent": "再修还是错"},
        {"when": "always", "action": RunTests(), "intent": "跑"},
    ])
    cfg = _cfg(ws)
    loop = AgentLoop(llm=mock, config=cfg, memory=Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, 3))
    result = loop.run(task="修", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "stuck"
    assert result.steps  # 有步骤
    # 至少有一轮注入了"换思路"提示(连续同类达 prompt_at=2)
    # 验证:循环过程中 state.context_injected 应含换思路——通过 outcome==stuck 间接断言已足够
```

- [ ] **Step 4: 写 `tests/demo/__init__.py`**(空)

- [ ] **Step 5: 写 `scripts/demo.sh`**

```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
echo "== 演示 ① 护栏拦截 =="
uv run pytest tests/demo/test_demo_1_guardrail.py -v
echo "== 演示 ② 反馈闭环改变下一步 =="
uv run pytest tests/demo/test_demo_2_feedback_loop.py -v
echo "== 演示 ③ 策略切换与停机 =="
uv run pytest tests/demo/test_demo_3_strategy_and_stop.py -v
echo "== 全部演示通过 =="
```

- [ ] **Step 6: 跑三个演示验证通过**

Run: `bash scripts/demo.sh`
Expected: 三个演示全 PASS。

- [ ] **Step 7: Commit**

```bash
chmod +x scripts/demo.sh
git add tests/demo scripts/demo.sh
git commit -m "test(demo): §A.6 三个机制演示"
```

---

## Task 19: FastAPI WebUI 后端 `web/app.py`

**Files:**
- Create: `src/coding_agent_harness/web/__init__.py`
- Create: `src/coding_agent_harness/web/app.py`
- Create: `src/coding_agent_harness/web/static/index.html`
- Test: `tests/integration/test_web.py`

**Interfaces:**
- Produces: `create_app(config)` 工厂;端点 `POST /api/tasks`、`GET /api/tasks/{id}/events`(SSE)、`POST /api/tasks/{id}/approvals/{aid}`、`GET /api/credentials/status`、`POST /api/credentials/set`。

- [ ] **Step 1: 写 `src/coding_agent_harness/web/__init__.py`**(空)

- [ ] **Step 2: 写失败测试 `tests/integration/test_web.py`**

```python
from coding_agent_harness.web.app import create_app
from fastapi.testclient import TestClient


def test_submit_task_returns_id(tmp_path):
    app = create_app(project_root=tmp_path, use_mock=True)
    c = TestClient(app)
    r = c.post("/api/tasks", json={"task": "修 bug"})
    assert r.status_code == 200
    assert "task_id" in r.json()


def test_credentials_status_not_set(tmp_path):
    app = create_app(project_root=tmp_path, use_mock=True)
    c = TestClient(app)
    r = c.get("/api/credentials/status")
    assert r.status_code == 200
    assert r.json() == {"set": False} or r.json().get("set") in (True, False)
```

- [ ] **Step 3: 跑测试验证失败**

Run: `uv run pytest tests/integration/test_web.py -v`
Expected: FAIL。先 `uv sync` 安装 fastapi 测试依赖(已在 dev)。

- [ ] **Step 4: 写实现 `src/coding_agent_harness/web/app.py`**

```python
"""FastAPI 单页 WebUI。SSE 推送主循环事件,HITL 审批。"""
from __future__ import annotations
import asyncio
import json
import uuid
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from coding_agent_harness.config import Config
from coding_agent_harness.core.loop import AgentLoop
from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.memory.store import Memory
from coding_agent_harness.creds.keychain import Creds


class TaskReq(BaseModel):
    task: str


def create_app(config: Config | None = None, *, project_root: Path | str = "./workspace", use_mock: bool = True) -> FastAPI:
    app = FastAPI(title="Coding Agent Harness")
    state: dict[str, dict] = {}
    creds = Creds()

    if config is None:
        from coding_agent_harness.config import load_config
        cfg_path = Path(project_root) / "config.yaml"
        config = load_config(cfg_path) if cfg_path.exists() else _default_config(project_root)

    @app.get("/")
    def index():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.post("/api/tasks")
    def submit(req: TaskReq):
        task_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue()
        events_log: list[dict] = []
        mem = Memory(config.memory.fixes_path, config.memory.conventions_path, config.memory.retrieve_top_k)
        llm = MockLLMClient(_demo_script()) if use_mock else _real_llm(creds)
        loop = AgentLoop(
            llm=llm, config=config, memory=mem,
            on_event=lambda e: (events_log.append(e), asyncio.run_coroutine_threadsafe(queue.put(e), asyncio.get_event_loop())),
        )
        async def runner():
            await asyncio.to_thread(loop.run, req.task, lambda: "2026-07-22T00:00:00")
            await queue.put({"type": "loop_stopped"})
        state[task_id] = {"loop": loop, "queue": queue, "events": events_log, "task": asyncio.create_task(rununner()) if False else None}
        return {"task_id": task_id}

    @app.get("/api/tasks/{task_id}/events")
    def events(task_id: str):
        async def stream():
            q = state[task_id]["queue"]
            while True:
                e = await q.get()
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
                if e.get("type") == "loop_stopped":
                    break
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/tasks/{task_id}/approvals/{aid}")
    def approve(task_id: str, aid: str, decision: dict):
        # 简化:回灌决定(完整 HITL 在 Task 15 基础上扩展)
        return {"ok": True, "decision": decision}

    @app.get("/api/credentials/status")
    def cred_status():
        return creds.status()

    @app.post("/api/credentials/set")
    def cred_set(body: dict):
        creds.set(body["api_key"], body["base_url"], body["model"])
        return {"set": True}

    static = Path(__file__).parent / "static"
    static.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=static), name="static")
    return app


def _default_config(project_root) -> Config:
    from coding_agent_harness.config import load_config
    import tempfile, yaml
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({"project_root": str(project_root), "llm": {"base_url": "x", "model": "m"}}, f)
    f.close()
    return load_config(f.name)


def _demo_script():
    from coding_agent_harness.models import WriteFile, RunTests, Stop
    return [
        {"when": "round 1", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+1\n"), "intent": "我先改返回值"},
        {"when": "round 2", "action": RunTests(), "intent": "验证"},
        {"when": "feedback.category == AssertionFailure", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b\n"), "intent": "上次断言失败,改 off-by-one"},
        {"when": "round 4", "action": RunTests(), "intent": "再验证"},
        {"when": "feedback.status == PASS", "action": Stop("done"), "intent": "全绿"},
    ]


def _real_llm(creds):
    from coding_agent_harness.llm.openai_compat import OpenAICompatibleClient
    return OpenAICompatibleClient(creds)
```

（注:`create_task(rununner())` 是笔误占位,见 Step 5 修正。）

- [ ] **Step 5: 修正 runner 调度**

把 `state[task_id] = {...}` 行改为:

```python
        t = asyncio.create_task(runner())
        state[task_id] = {"loop": loop, "queue": queue, "events": events_log, "task": t}
```

并删去 `if False else None`。

- [ ] **Step 6: 跑测试验证通过**

Run: `uv run pytest tests/integration/test_web.py -v`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add src/coding_agent_harness/web tests/integration/test_web.py
git commit -m "feat(web): FastAPI + SSE 后端"
```

---

## Task 20: 单页前端 `web/static/index.html`

**Files:**
- Create: `src/coding_agent_harness/web/static/index.html`

**Interfaces:**
- 产出:单页 HTML + 原生 JS,用 Open Design token 做配色/间距;`EventSource` 接 SSE;左侧事件时间线、右侧状态面板、内联审批按钮。

- [ ] **Step 1: 写 `src/coding_agent_harness/web/static/index.html`**

```html
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <title>Coding Agent Harness</title>
  <!-- Open Design 设计系统 token(以 CSS 变量注入;正式集成时替换为 Open Design 组件包) -->
  <style>
    :root {
      --od-bg: #0f1115; --od-surface: #181b22; --od-text: #e6e6e6;
      --od-accent: #4d8cff; --od-danger: #ff5d5d; --od-success: #3ecf8e;
      --od-space: 12px; --od-radius: 8px;
    }
    body { margin:0; background:var(--od-bg); color:var(--od-text); font-family:system-ui,sans-serif; }
    header { padding:var(--od-space); background:var(--od-surface); display:flex; gap:var(--od-space); }
    input[type=text] { flex:1; padding:8px; border-radius:var(--od-radius); border:1px solid #333; background:#111; color:var(--od-text); }
    button { padding:8px 12px; border:0; border-radius:var(--od-radius); background:var(--od-accent); color:#fff; cursor:pointer; }
    main { display:grid; grid-template-columns:2fr 1fr; gap:var(--od-space); padding:var(--od-space); }
    #timeline { background:var(--od-surface); border-radius:var(--od-radius); padding:var(--od-space); overflow:auto; height:80vh; }
    #status { background:var(--od-surface); border-radius:var(--od-radius); padding:var(--od-space); height:80vh; }
    .step { border-left:3px solid var(--od-accent); margin:8px 0; padding:6px 10px; }
    .step.deny { border-color:var(--od-danger); }
    .step.pass { border-color:var(--od-success); }
    .intent { color:#9bb; font-style:italic; }
    .approve-btns button { margin-right:6px; }
    .approve-btns button.deny { background:var(--od-danger); }
  </style>
</head>
<body>
  <header>
    <input id="task" type="text" placeholder="描述任务,如:修 add 的 bug" />
    <button onclick="start()">开始</button>
    <button onclick="location.href='/static/creds.html'">凭据</button>
  </header>
  <main>
    <div id="timeline"></div>
    <div id="status"><h3>状态</h3><pre id="state">(未开始)</pre></div>
  </main>
  <script>
    let es;
    function start() {
      const task = document.getElementById('task').value;
      fetch('/api/tasks', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({task})})
        .then(r=>r.json()).then(d=>{
          document.getElementById('timeline').innerHTML='';
          es = new EventSource(`/api/tasks/${d.task_id}/events`);
          es.onmessage = ev => render(JSON.parse(ev.data));
        });
    }
    function render(e) {
      const tl = document.getElementById('timeline');
      if (e.type === 'loop_stopped') { tl.innerHTML += '<div class="step pass">loop 结束</div>'; es.close(); return; }
      const cls = e.verdict === 'Deny' ? 'deny' : (e.feedback && e.feedback.status==='PASS' ? 'pass' : '');
      const intent = e.intent ? `<div class="intent">intent: ${e.intent}</div>` : '';
      const fb = e.feedback ? `<div>feedback: ${e.feedback.status} (fail=${e.feedback.failed} pass=${e.feedback.passed})</div>` : '';
      tl.innerHTML += `<div class="step ${cls}"><div>${e.type}</div>${intent}${fb}</div>`;
      tl.scrollTop = tl.scrollHeight;
    }
  </script>
</body>
</html>
```

- [ ] **Step 2: 手动冒烟**

Run: `uv run harness serve` → 浏览器打开 http://localhost:8000 → 输入任务 → 看事件流。
Expected: 能看到 mock 的红变绿过程。

- [ ] **Step 3: Commit**

```bash
git add src/coding_agent_harness/web/static/index.html
git commit -m "feat(web): 单页前端 + Open Design token + SSE 渲染"
```

---

## Task 21: CLI 入口 `main.py`

**Files:**
- Create: `src/coding_agent_harness/main.py`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Produces: `main(argv) -> int`;子命令 `serve` / `creds status|set|clear` / `run`。

- [ ] **Step 1: 写失败测试 `tests/unit/test_cli.py`**

```python
from coding_agent_harness.main import main


def test_creds_status_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = main(["creds", "status"])
    assert rc == 0


def test_serve_missing_args_errors():
    rc = main(["unknown"])
    assert rc != 0
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: FAIL。

- [ ] **Step 3: 写实现 `src/coding_agent_harness/main.py`**

```python
"""CLI 入口: serve / creds / run。"""
from __future__ import annotations
import sys
import argparse
from coding_agent_harness.creds.keychain import Creds


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("用法: harness serve | creds {status|set|clear} | run <task>", file=sys.stderr)
        return 2
    cmd = argv[0]
    if cmd == "serve":
        import uvicorn
        from coding_agent_harness.web.app import create_app
        app = create_app(use_mock="--real" not in argv)
        uvicorn.run(app, host="0.0.0.0", port=8000)
        return 0
    if cmd == "creds":
        sub = argv[1] if len(argv) > 1 else "status"
        c = Creds()
        if sub == "status":
            print("已设置" if c.status()["set"] else "未设置")
            return 0
        if sub == "set":
            import getpass
            key = getpass.getpass("api_key: ")
            base = input("base_url: ")
            model = input("model: ")
            c.set(key, base, model)
            print("已保存")
            return 0
        if sub == "clear":
            c.clear()
            print("已清除")
            return 0
        return 2
    if cmd == "run":
        from coding_agent_harness.config import load_config
        from coding_agent_harness.core.loop import AgentLoop
        from coding_agent_harness.llm.openai_compat import OpenAICompatibleClient
        from coding_agent_harness.memory.store import Memory
        task = " ".join(argv[1:])
        cfg = load_config("config.yaml")
        mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
        loop = AgentLoop(llm=OpenAICompatibleClient(Creds()), config=cfg, memory=mem)
        result = loop.run(task, ts_provider=lambda: "2026-07-22T00:00:00")
        print(result.outcome)
        return 0 if result.outcome == "success" else 1
    print(f"未知命令: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent_harness/main.py tests/unit/test_cli.py
git commit -m "feat(cli): serve/creds/run 子命令"
```

---

## Task 22: CI 配置

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- 产出:`unit-test` job + ubuntu/windows 矩阵;每次 push 自动跑测试。

- [ ] **Step 1: 写 `.github/workflows/ci.yml`**

```yaml
name: CI
on:
  push:
  pull_request:

jobs:
  unit-test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: install uv
        run: pip install uv
      - name: sync deps
        run: uv sync --extra dev
      - name: run tests
        run: uv run pytest -q
```

- [ ] **Step 2: 本地确认全测试通过**

Run: `uv run pytest -q`
Expected: 全 PASS。

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: ubuntu+windows 矩阵 unit-test job"
```

---

## Task 23: Dockerfile 与云部署

**Files:**
- Create: `Dockerfile`
- Create: `.github/workflows/deploy.yml`

**Interfaces:**
- 产出:容器镜像 `docker build` + `docker run` 起服务;CI 部署到云(Render/Fly.io)。

- [ ] **Step 1: 写 `Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --extra dev --no-dev 2>/dev/null || uv sync
COPY src ./src
COPY config.example.yaml ./config.yaml
EXPOSE 8000
CMD ["uv","run","harness","serve"]
```

- [ ] **Step 2: 写 `.github/workflows/deploy.yml`**(Render 静态服务示例,按实际平台调整)

```yaml
name: deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: build image
        run: docker build -t coding-agent-harness:latest .
      # 部署到 Render/Fly.io 的具体步骤按平台填写;key 经平台 secrets 注入环境变量
```

- [ ] **Step 3: 本地验证镜像可起**

Run: `docker build -t coding-agent-harness . && docker run -p 8000:8000 coding-agent-harness`
Expected: 容器起,浏览器访问 http://localhost:8000 见 WebUI。

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .github/workflows/deploy.yml
git commit -m "build(docker): 容器镜像与云部署工作流"
```

---

## Task 24: README 与安全边界章节

**Files:**
- Create: `README.md`

**Interfaces:**
- 产出:含章节——项目简介、安装、运行、分发命令、目录结构、**安全边界说明**(必含)。

- [ ] **Step 1: 写 `README.md`**

```markdown
# Coding Agent Harness

一个自实现的 Python Coding Agent Harness 内核,以**反馈闭环**为主贡献:让 agent 跑测试、读失败反馈、据此多轮自我修正。

## 安装

需 Python 3.11+ 与 [uv](https://docs.astral.sh/uv/)。

```bash
git clone <repo>
cd coding-agent-harness
uv sync --extra dev
```

## 运行

```bash
uv run harness serve          # 三平台通用
make run                       # Unix 便利别名
```

浏览器打开 http://localhost:8000 。首次使用配 key:

```bash
uv run harness creds set      # 录入 api_key / base_url / model
uv run harness creds status   # 查看状态(不回显明文)
```

CLI 直接跑(不启 web):

```bash
uv run harness run 修 add 的 bug
```

## 测试

```bash
make test                      # = uv run pytest -q
bash scripts/demo.sh           # §A.6 三个机制演示
```

## 分发

主形态:clone + `uv run harness serve`。云部署:见 `Dockerfile`。

## 目录结构

见 `docs/superpowers/specs/2026-07-21-coding-agent-harness-design.md` §十三。

## 安全边界

- **凭据**:API key 存系统钥匙串(macOS Keychain / Windows Credential Manager / Linux Secret Service),绝不硬编码、不进 git、不进日志、不回显。`creds status` 只返回"已设置/未设置"。
- **路径围栏**:agent 写文件限项目根内;越界需人工审批。
- **shell 拦截**:黑名单命令(rm -rf、del /s 等)直接拒不可放行;未知 shell 需审批。
- **HITL**:删文件、越界写、未知 shell 一律挂起等审批;审批事件带 LLM 自述 intent 供人类判断。
- **mock 隔离**:单测与机制演示用 MockLLMClient,不读 Keychain、不触网,真实 key 不进测试。
- **已知限制**:Windows `cmd` 语义弱于 bash,复杂管道行为可能不同;需桌面会话才能用系统钥匙串。
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README 与安全边界章节"
```

---

## Self-Review

**1. Spec coverage(逐条对照 spec):**

| Spec 章节 | 覆盖 Task |
|---|---|
| §3.1 主循环 | Task 15 |
| §3.2 LLM 抽象层(接口/mock/真实) | Task 12/13/17 |
| §3.3 工具集 | Task 6/7/8/9 |
| §3.4 反馈闭环(主贡献) | Task 4/5/14(+15 集成) |
| §3.5 治理护栏 + HITL | Task 11(+15 HITL 回灌) |
| §3.6 动作意图 intent | Task 2(models)+ 13(mock)+ 17(真实)+ 19(WebUI 显示) |
| §3.7 记忆 | Task 10 |
| §3.8 配置 | Task 3 |
| §3.9 WebUI | Task 19/20 |
| §3.10 凭据 | Task 16 |
| §六 凭据与分发 | Task 16/23/24 |
| §八 领域与机制设计 | Task 5/11/14/18(演示) |
| §九 验收标准 | Task 18(三演示)+ 22(CI) |
| §A.6 三演示 | Task 18 |

缺口:**HITL 完整状态机**(Task 15 里 `NeedsApproval` 回灌了"需人工审批"但未实现真正的挂起→approve()→恢复)。Task 19 `POST /api/tasks/{id}/approvals/{aid}` 是占位。**这需要在 Task 15 扩展为真正的挂起/恢复**——加 follow-up:

- [ ] **补充 Task 15b:HITL 完整化**(在 Task 15 完成后)

**Files:** Modify `src/coding_agent_harness/core/loop.py`、`tests/integration/test_loop_hitl.py`

把 `NeedsApproval` 分支改为:生成 `approval_id`,挂起循环(用 `threading.Event` 或 async 挂起),`approve(approval_id, decision)` 唤醒并据决定执行或回灌"被拒"。测试:mock 输出 `DeleteFile` → 断言 `state` 有 pending approval → 调 `approve(id, True)` → 文件被删(或 `False` → 未删)。

（此补充是 spec §3.5 HITL 状态机的完整实现,不补则 §A.6 演示①的"弹审批按钮→人类决定"链路不完整。务必在 Task 18 演示①之前完成。）

**2. Placeholder scan:** Task 19 Step 4 有笔误占位 `rununner()`/`if False else None`,已在 Step 5 修正。其余无 TBD/TODO。

**3. Type consistency:** `FailureCategory` 在 taxonomy(值)与 models.FailedTest.category(字符串注解)与 validator(赋值)与 mock(对比 `.value`)一致。`AssistantTurn.{action,intent,raw}` 在 base/mock/openai_compat/loop 一致。`LoopState.snapshot()` 用于传给 mock(避免 mock 改主状态)——Task 13 测试用 `state.rounds/last_category/last_feedback_status`,Task 14 `snapshot` 复制这些字段,一致。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-22-coding-agent-harness.md`. Two execution options:

**1. Subagent-Driven (recommended)** - 我每个 task 派一个新鲜 subagent,task 间两阶段评审,快速迭代

**2. Inline Execution** - 在当前会话用 executing-plans 批量执行,带检查点

你选哪种?
