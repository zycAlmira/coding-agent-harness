"""CLI 入口: serve / creds / run。

- serve: 启动 FastAPI WebUI(uvicorn),默认 mock LLM 演示,--real 用真实客户端。
- creds {status|set|clear}: 凭据经 keychain,api_key 用 getpass 隐藏录入不回显。
- run <task>: 用真实 LLM 跑一次任务,打印 outcome。
"""
from __future__ import annotations
import sys
from coding_agent_harness.creds.keychain import Creds


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("用法: harness serve [--real] | creds {status|set|clear} | run <task>", file=sys.stderr)
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
        loop = AgentLoop(llm=OpenAICompatibleClient(Creds()), config=cfg, memory=mem)
        result = loop.run(task, ts_provider=lambda: "2026-07-22T00:00:00")
        print(result.outcome)
        return 0 if result.outcome == "success" else 1
    print(f"未知命令: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
