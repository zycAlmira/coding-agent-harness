"""FastAPI 单页 WebUI。SSE 推送主循环事件,HITL 审批,凭据管理。"""
from __future__ import annotations
import asyncio
import json
import uuid
import tempfile
from pathlib import Path
import yaml
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from coding_agent_harness.config import Config, load_config
from coding_agent_harness.core.loop import AgentLoop
from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.memory.store import Memory
from coding_agent_harness.creds.keychain import Creds


class TaskReq(BaseModel):
    task: str


class ApproveReq(BaseModel):
    decision: bool


class CredSetReq(BaseModel):
    api_key: str
    base_url: str
    model: str


def create_app(
    config: Config | None = None,
    *,
    project_root: Path | str = "./workspace",
    use_mock: bool = True,
) -> FastAPI:
    """构造 WebUI app。use_mock=True 用脚本化 mock LLM(不触网,供演示/测试);
    use_mock=False 用真实 OpenAI 兼容客户端(凭据从 keychain 读)。"""
    app = FastAPI(title="Coding Agent Harness")
    state: dict[str, dict] = {}
    creds = Creds()

    if config is None:
        config = _default_config(project_root)

    @app.get("/")
    def index():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.post("/api/tasks")
    async def submit(req: TaskReq):
        task_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue()
        events_log: list[dict] = []
        # 捕获当前运行中的 event loop,on_event 在 agent.run 的 to_thread 线程里
        # 被调,需跨线程把事件塞回此 loop 的 queue。
        loop = asyncio.get_running_loop()

        def on_event(e: dict) -> None:
            events_log.append(e)
            try:
                asyncio.run_coroutine_threadsafe(queue.put(e), loop)
            except RuntimeError:
                # loop 已关闭(测试 teardown 场景):事件仍进 events_log,不崩。
                pass

        mem = Memory(config.memory.fixes_path, config.memory.conventions_path, config.memory.retrieve_top_k)
        llm = MockLLMClient(_demo_script()) if use_mock else _real_llm(creds)
        agent = AgentLoop(llm=llm, config=config, memory=mem, on_event=on_event)

        async def runner():
            await asyncio.to_thread(agent.run, req.task, lambda: "2026-07-22T00:00:00")
            await queue.put({"type": "loop_stopped"})

        t = asyncio.create_task(runner())
        state[task_id] = {"loop": agent, "queue": queue, "events": events_log, "task": t}
        return {"task_id": task_id}

    @app.get("/api/tasks/{task_id}/events")
    async def events(task_id: str):
        async def stream():
            q = state[task_id]["queue"]
            while True:
                e = await q.get()
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
                if e.get("type") == "loop_stopped":
                    break
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/tasks/{task_id}/approvals/{aid}")
    def approve(task_id: str, aid: str, req: ApproveReq):
        agent = state[task_id]["loop"]
        agent.approve(aid, req.decision)
        return {"ok": True, "approved": req.decision}

    @app.get("/api/credentials/status")
    def cred_status():
        return creds.status()

    @app.post("/api/credentials/set")
    def cred_set(req: CredSetReq):
        creds.set(req.api_key, req.base_url, req.model)
        return {"set": True}

    static = Path(__file__).parent / "static"
    static.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=static), name="static")
    return app


def _default_config(project_root) -> Config:
    """无 config.yaml 时用最小默认(project_root + llm 占位);其余取 dataclass 默认。"""
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({"project_root": str(project_root), "llm": {"base_url": "x", "model": "m"}}, f)
    f.close()
    return load_config(f.name)


def _demo_script():
    """WebUI 演示脚本:红→绿(错值起步 → 据 AssertionFailure 反馈改对 → PASS)。
    round4 排在 feedback.category 前,避免 round3 被反馈分支抢占。"""
    from coding_agent_harness.models import WriteFile, RunTests, Stop
    return [
        {"when": "round 1", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+2\n"), "intent": "我先改返回值"},
        {"when": "round 2", "action": RunTests(), "intent": "验证修复"},
        {"when": "round 4", "action": RunTests(), "intent": "再验证"},
        {"when": "feedback.category == AssertionFailure", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+1\n"), "intent": "上次断言失败,改 off-by-one"},
        {"when": "feedback.status == PASS", "action": Stop("done"), "intent": "测试全绿,完成"},
    ]


def _real_llm(creds):
    from coding_agent_harness.llm.openai_compat import OpenAICompatibleClient
    return OpenAICompatibleClient(creds)
