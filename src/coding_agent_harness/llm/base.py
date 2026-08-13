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
