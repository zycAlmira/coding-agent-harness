"""真实 OpenAI 兼容客户端。底层零件,不寄生 agent 框架。key 不进日志。"""
from __future__ import annotations
import json
import logging
import httpx
from coding_agent_harness.models import (
    AssistantTurn, Action, WriteFile, DeleteFile, RunShell, RunTests, ReadFile, ListDir, SearchFile, Stop, Respond,
)

log = logging.getLogger(__name__)

_ACTION_BUILDERS = {
    "write_file": lambda a: WriteFile(a["path"], a["content"]),
    "delete_file": lambda a: DeleteFile(a["path"]),
    "run_shell": lambda a: RunShell(a["cmd"]),
    "run_tests": lambda a: RunTests(a.get("path"), a.get("test_command")),
    "read_file": lambda a: ReadFile(a["path"], a.get("offset"), a.get("lines")),
    "list_dir": lambda a: ListDir(a["path"], a.get("recursive")),
    "search_file": lambda a: SearchFile(a["path"], a["pattern"], a.get("context")),
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
        content = msg.get("content") or ""
        if not tcs:
            # LLM 输出纯文本(回答问题/总结工作等):返回 Respond 动作,
            # 主循环将其发送给前端并继续,LLM 可在后续轮调用 stop 或继续操作。
            if content.strip():
                return AssistantTurn(action=Respond(content[:2000]), intent="回复", raw=str(msg), text=content[:2000])
            # 空内容:退化为 stop(罕见,可能是 API 异常)。
            return AssistantTurn(action=Stop("no_tool_call"), intent="", raw=str(msg))
        tc = tcs[0]["function"]
        action, intent = parse_tool_call(tc)
        # 工具调用前的文字说明(content 与 tool_calls 并存):随动作一并返回,
        # 由主循环展示给用户——否则"只有工具调用没有回复"(真实 LLM 常同时输出)。
        text = content.strip()[:2000] if content.strip() else None
        log.debug("llm intent=%s action=%s", intent, type(action).__name__)  # key 不进日志
        return AssistantTurn(action=action, intent=intent, raw=str(tc), text=text)
