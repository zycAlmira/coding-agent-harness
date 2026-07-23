"""FastAPI 单页 WebUI。SSE 推送主循环事件,HITL 审批,凭据管理。"""
from __future__ import annotations
import asyncio
import json
import threading
import uuid
import tempfile
from pathlib import Path
import yaml
from fastapi import FastAPI, HTTPException
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
    mock_script: list | None = None,
) -> FastAPI:
    """构造 WebUI app。use_mock=True 用脚本化 mock LLM(不触网,供演示/测试);
    use_mock=False 用真实 OpenAI 兼容客户端(凭据从 keychain 读)。
    mock_script 可注入自定义 mock 脚本(测试用,如触发 DeleteFile 审批)。"""
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
        # 捕获当前运行中的 event loop,on_event 在 agent.run 的工作线程里被调,
        # 需跨线程把事件塞回此 loop 的 queue(SSE 消费时排空)。
        loop = asyncio.get_running_loop()

        def emit(e: dict) -> None:
            """跨线程把事件塞进 event loop 的 queue(供 SSE 消费);用 call_soon_threadsafe
            + put_nowait(同步回调,不创建 coroutine),避免 loop 未运行时产生
            'coroutine never awaited' 警告。事件同时进 events_log 兜底。"""
            events_log.append(e)
            try:
                loop.call_soon_threadsafe(queue.put_nowait, e)
            except RuntimeError:
                # loop 已关闭(测试 teardown):事件已在 events_log,不崩。
                pass

        mem = Memory(config.memory.fixes_path, config.memory.conventions_path, config.memory.retrieve_top_k)
        llm = MockLLMClient(mock_script if mock_script is not None else _demo_script()) if use_mock else _real_llm(creds)
        # hitl_enabled=True 激活 §A.6 ① 审批链路:NeedsApproval 时挂起→发 pending_approval
        # 事件→前端弹按钮→POST /approvals→approve 唤醒。red→green demo 无 DeleteFile 不会触发。
        agent = AgentLoop(llm=llm, config=config, memory=mem, on_event=emit, hitl_enabled=True)

        def worker():
            # 在普通线程(非 asyncio task)里跑 agent.run,避免 TestClient 的 anyio
            # task group 在请求结束时取消/等待未完成 task 致 submit 挂起。HITL 挂起
            # (threading.Event)在此线程阻塞,不依赖 event loop;approve 经 /approvals
            # 端点唤醒。try/except/finally 保证 loop_stopped 一定发出(SSE 不无限阻塞)。
            try:
                agent.run(req.task, lambda: "2026-07-22T00:00:00")
            except Exception as e:  # noqa: BLE001 给前端一个可见错误,不吞
                emit({"type": "error", "msg": str(e)})
            finally:
                emit({"type": "loop_stopped"})

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        state[task_id] = {"loop": agent, "queue": queue, "events": events_log, "thread": thread}
        return {"task_id": task_id}

    @app.get("/api/tasks/{task_id}/events")
    async def events(task_id: str):
        entry = state.get(task_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown task_id")

        async def stream():
            q = entry["queue"]
            while True:
                e = await q.get()
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
                if e.get("type") == "loop_stopped":
                    break
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/tasks/{task_id}/approvals/{aid}")
    def approve(task_id: str, aid: str, req: ApproveReq):
        entry = state.get(task_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown task_id")
        agent = entry["loop"]
        agent.approve(aid, req.decision)
        return {"ok": True, "approved": req.decision}

    @app.get("/api/tasks/{task_id}/pending")
    def pending(task_id: str):
        """非阻塞返回当前 pending 审批(供前端/CLI 轮询);无则 {"pending": false}。"""
        entry = state.get(task_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown task_id")
        snap = entry["loop"].current_pending()
        if not snap:
            return {"pending": False}
        return {"pending": True, **snap}

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
    try:
        yaml.safe_dump({"project_root": str(project_root), "llm": {"base_url": "x", "model": "m"}}, f)
        f.close()
        return load_config(f.name)
    finally:
        try:
            Path(f.name).unlink()
        except OSError:
            pass


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
