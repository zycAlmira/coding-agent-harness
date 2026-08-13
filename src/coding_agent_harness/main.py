"""CLI 入口: serve / creds / run。

- serve: 启动 FastAPI WebUI(uvicorn),默认 mock LLM 演示,--real 用真实客户端。
- creds {status|set|clear}: 凭据经 keychain,api_key 用 getpass 隐藏录入不回显。
- run <task>: 用真实 LLM 跑一次任务,打印 outcome。
"""
from __future__ import annotations
import os
import sys
from coding_agent_harness.creds.keychain import Creds


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("用法: harness serve [--real] [--project-root <path>] | creds {status|set|clear} | run <task> | chat", file=sys.stderr)
        return 2
    cmd = argv[0]
    if cmd == "chat":
        return _chat(argv[1:])
    if cmd == "serve":
        import uvicorn
        from coding_agent_harness.web.app import create_app
        use_mock = "--real" not in argv
        # --project-root <path>:指定 agent 工作目录,默认 ./workspace;
        # 环境变量 HARNESS_PROJECT_ROOT 可覆盖(容器部署设默认演示项目)。
        root = os.environ.get("HARNESS_PROJECT_ROOT", "./workspace")
        if "--project-root" in argv:
            idx = argv.index("--project-root")
            if idx + 1 < len(argv):
                root = argv[idx + 1]
        app = create_app(use_mock=use_mock, project_root=root)
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
        print(f"未知子命令: {sub}", file=sys.stderr)
        return 2
    if cmd == "run":
        from coding_agent_harness.config import load_config
        from coding_agent_harness.core.loop import AgentLoop
        from coding_agent_harness.llm.openai_compat import OpenAICompatibleClient
        from coding_agent_harness.memory.store import Memory
        task = " ".join(argv[1:])
        try:
            cfg = load_config("config.yaml")
        except (FileNotFoundError, OSError) as e:
            print(f"无法读取 config.yaml: {e}", file=sys.stderr)
            print("提示:先 `harness creds set` 录入凭据,并准备 config.yaml。", file=sys.stderr)
            return 2
        mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)

        def _on_event(e: dict) -> None:
            # CLI 输出 agent 过程:文字回复 / 工具动作,让用户看到做了什么。
            if e.get("type") == "response" and e.get("text"):
                print(f"🤖 {e['text']}", flush=True)
            elif e.get("type") == "action":
                icon = {"ReadFile": "📖", "WriteFile": "✏️", "RunTests": "🧪",
                        "ListDir": "📂", "SearchFile": "🔍", "RunShell": "⚡"}.get(e.get("action", ""), "🔧")
                path = e.get("path") or ""
                print(f"  {icon} {e.get('action')} {path} | {e.get('intent', '')}", flush=True)

        loop = AgentLoop(llm=OpenAICompatibleClient(Creds()), config=cfg, memory=mem, on_event=_on_event)
        result = loop.run(task, ts_provider=lambda: "2026-07-22T00:00:00")
        print(f"\n==> outcome: {result.outcome}")
        return 0 if result.outcome == "success" else 1
    print(f"未知命令: {cmd}", file=sys.stderr)
    return 2


# ── Claude Code 式交互 REPL ──────────────────────────────
# 颜色(终端 ANSI;非 TTY 自动降级)
def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


_CYAN, _GREEN, _YELLOW, _RED, _DIM = "36", "32", "33", "31", "2"

_ACTION_ICON = {"ReadFile": "📖", "WriteFile": "✏️", "DeleteFile": "🗑️",
                "ListDir": "📂", "SearchFile": "🔍", "RunTests": "🧪",
                "RunShell": "⚡", "Stop": "🛑", "Respond": "💬"}


def _chat(argv: list[str]) -> int:
    """交互式 REPL:连续输入任务,agent 流式执行,上下文保持。

    与 WebUI 对话方式一致:同一 AgentLoop 实例连续 run,每轮自动把
    上一轮 conversation_history 带进下一轮(多轮上下文保持)。
    事件流(response/action)打印到终端,还原 WebUI 的对话呈现。
    需 config.yaml + creds set(真实 LLM);exit/quit 退出。
    """
    from coding_agent_harness.config import load_config
    from coding_agent_harness.core.loop import AgentLoop
    from coding_agent_harness.memory.store import Memory
    from coding_agent_harness.llm.openai_compat import OpenAICompatibleClient

    try:
        cfg = load_config("config.yaml")
    except (FileNotFoundError, OSError) as e:
        print(f"无法读取 config.yaml: {e}", file=sys.stderr)
        print("提示:先 `harness creds set` 录入凭据,并准备 config.yaml。", file=sys.stderr)
        return 2

    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)

    def _emit(e: dict) -> None:
        # 还原 WebUI 对话呈现:文字回复气泡 + 工具动作行
        if e.get("type") == "response" and e.get("text"):
            print(f"{_c(_CYAN, '🤖')} {e['text']}", flush=True)
        elif e.get("type") == "action":
            icon = _ACTION_ICON.get(e.get("action", ""), "🔧")
            path = e.get("path") or ""
            intent = e.get("intent", "")
            line = f"  {icon} {_c(_GREEN, e.get('action', ''))} {_c(_DIM, path)} | {intent}"
            if e.get("verdict") == "Deny":
                line = f"  {icon} {_c(_RED, e.get('action', ''))} 🚫 {_c(_DIM, e.get('error', ''))}"
            print(line, flush=True)

    loop = AgentLoop(llm=OpenAICompatibleClient(Creds()), config=cfg, memory=mem, on_event=_emit)
    print(_c(_YELLOW, "Coding Agent Harness — 对话模式"))
    print(_c(_DIM, "输入任务开始;exit/quit 退出;Ctrl+C 中断。"))
    while True:
        try:
            task = input(_c(_GREEN, "❯ "))
        except (EOFError, KeyboardInterrupt):
            print()
            break
        task = task.strip()
        if not task:
            continue
        if task in ("exit", "quit"):
            break
        try:
            result = loop.run(task, ts_provider=lambda: "2026-07-22T00:00:00")
            print(f"\n{_c(_DIM, '==> outcome:')} {_c(_YELLOW, result.outcome)}", flush=True)
        except Exception as e:
            print(f"{_c(_RED, '!!')} {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
