"""声明式配置加载。纯函数,可单测。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class LLMConfig:
    """LLM 抽象层配置。"""

    base_url: str
    model: str
    provider: str = "openai-compatible"


@dataclass(frozen=True)
class GuardrailsConfig:
    """治理护栏配置:回合上限、重复类别处置、无变化停机、审批超时、shell 黑白名单。

    max_rounds:软上限——达到时注入「尽快收尾」提示,不终止(复杂任务可继续)。
    hard_max_rounds:硬上限——真正强制终止的安全阀(防死循环;stuck 兜底通常更早触发)。
    """

    max_rounds: int = 20
    hard_max_rounds: int = 60
    same_category_prompt_at: int = 2
    same_category_stop_at: int = 3
    no_change_stop_at: int = 2
    approval_timeout_sec: int = 300
    shell_blacklist: list[str] = field(default_factory=lambda: ["rm -rf"])
    shell_whitelist: list[str] = field(default_factory=lambda: ["pytest"])


@dataclass(frozen=True)
class FeedbackConfig:
    """反馈校验器配置:pytest 参数与 traceback 摘录行数。"""

    pytest_args: list[str] = field(
        default_factory=lambda: ["--tb=short", "-q"]
    )
    max_traceback_excerpt_lines: int = 8


@dataclass(frozen=True)
class MemoryConfig:
    """记忆读写配置:fixes/conventions 路径与检索 top-k。"""

    fixes_path: str = "./memory/fixes.json"
    conventions_path: str = "./memory/conventions.json"
    retrieve_top_k: int = 3


@dataclass(frozen=True)
class Config:
    """顶层配置聚合。各子配置带默认值,缺省段时取默认。"""

    project_root: Path
    llm: LLMConfig
    guardrails: GuardrailsConfig = field(default_factory=GuardrailsConfig)
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)


def _filter_known(raw: dict, cls) -> dict:
    """只保留目标 dataclass 已知字段,忽略 YAML 中多余键。

    若某已知字段在 YAML 中显式写空(如 `max_rounds:` 不给值),`raw[k]` 为
    `None`,此处跳过以让 dataclass 默认值生效,避免 `None` 覆盖默认导致后续消费崩溃。
    """
    return {
        k: raw[k]
        for k in raw
        if k in cls.__dataclass_fields__ and raw[k] is not None
    }


def load_config(path: Path | str) -> Config:
    """从 YAML 文件加载配置并构造冻结 dataclass。

    缺省的子段以各自默认值填充;子段内缺省字段同样取默认值。
    """
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
        guardrails=GuardrailsConfig(**_filter_known(gr_raw, GuardrailsConfig)),
        feedback=FeedbackConfig(**_filter_known(fb_raw, FeedbackConfig)),
        memory=MemoryConfig(**_filter_known(mem_raw, MemoryConfig)),
    )
