"""FastAPI 单页 WebUI。SSE 推送主循环事件,HITL 审批,凭据管理,任务历史,工作区浏览。"""
from __future__ import annotations
import asyncio
import json
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
import yaml
from fastapi import FastAPI, HTTPException, Query
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
    workspace: str | None = None  # 可选:覆盖默认工作区


class ApproveReq(BaseModel):
    decision: bool


class CredSetReq(BaseModel):
    api_key: str
    base_url: str
    model: str


class ModelSwitchReq(BaseModel):
    model: str


class WorkspaceSwitchReq(BaseModel):
    workspace: str


class ModeSwitchReq(BaseModel):
    mode: str


# 常用模型列表(供前端下拉选择)
_KNOWN_MODELS = [
    {"provider": "DeepSeek", "models": ["deepseek-chat", "deepseek-coder"]},
    {"provider": "OpenAI", "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]},
    {"provider": "通义千问", "models": ["qwen-turbo", "qwen-plus", "qwen-max"]},
    {"provider": "Moonshot", "models": ["moonshot-v1-8k", "moonshot-v1-32k"]},
    {"provider": "智谱", "models": ["glm-4", "glm-4-flash"]},
]


def _build_file_tree(root: Path, rel: Path | None = None, depth: int = 0) -> dict:
    """安全构建文件树,限制深度和类型,禁止越界。"""
    if rel is None:
        rel = root
    target = root / rel
    try:
        target = target.resolve()
        root_resolved = root.resolve()
        if not str(target).startswith(str(root_resolved)):
            return {"name": rel.name, "path": str(rel), "type": "error", "error": "越界"}
    except (OSError, ValueError):
        return {"name": rel.name, "path": str(rel), "type": "error", "error": "无法解析"}

    name = target.name
    if target.is_file():
        return {"name": name, "path": str(rel), "type": "file"}

    if target.is_dir():
        if depth >= 3:
            return {"name": name, "path": str(rel), "type": "dir", "children": None, "truncated": True}
        children = []
        try:
            entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return {"name": name, "path": str(rel), "type": "dir", "children": [], "error": "无权限"}
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.name in ("__pycache__", "node_modules", ".venv", "venv", ".git", "dist", ".pytest_cache"):
                continue
            if entry.is_dir():
                child = _build_file_tree(root, rel / entry.name, depth + 1)
                children.append(child)
            elif entry.is_file() and entry.suffix in (
                ".py", ".md", ".yaml", ".yml", ".txt", ".json", ".toml",
                ".cfg", ".ini", ".sh", ".html", ".css", ".js", ".ts", ".rs",
                ".go", ".java", ".c", ".cpp", ".h", ".Dockerfile", ".dockerignore",
            ):
                children.append({"name": entry.name, "path": str(rel / entry.name), "type": "file"})
        return {"name": name, "path": str(rel), "type": "dir", "children": children}
    return {"name": name, "path": str(rel), "type": "unknown"}


def create_app(
    config: Config | None = None,
    *,
    project_root: Path | str = "./workspace",
    use_mock: bool = True,
    mock_script: list | None = None,
) -> FastAPI:
    app = FastAPI(title="Coding Agent Harness")
    tasks_state: dict[str, dict] = {}
    creds = Creds()
    # 可变工作区(运行时可通过 UI 切换)
    _workspace: dict[str, str] = {"path": str(project_root)}
    # 任务历史(内存)
    _history: list[dict] = []
    # 当前模式
    _mode: dict[str, bool] = {"mock": use_mock}

    if config is None:
        config = _default_config(str(project_root))

    def _make_config() -> Config:
        """用当前工作区创建配置。"""
        return _default_config(_workspace["path"])

    @app.get("/")
    def index():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    # ── 任务提交 ──
    @app.post("/api/tasks")
    async def submit(req: TaskReq):
        task_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue()
        events_log: list[dict] = []
        loop = asyncio.get_running_loop()

        def emit(e: dict) -> None:
            events_log.append(e)
            try:
                loop.call_soon_threadsafe(queue.put_nowait, e)
            except RuntimeError:
                pass

        ws = req.workspace or _workspace["path"]
        cfg = _default_config(ws)
        mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
        llm = (
            MockLLMClient(mock_script if mock_script is not None else _demo_script())
            if _mode["mock"]
            else _real_llm(creds)
        )
        agent = AgentLoop(llm=llm, config=cfg, memory=mem, on_event=emit, hitl_enabled=True)

        def worker():
            result = None
            ts = datetime.now(timezone.utc).isoformat()
            try:
                result = agent.run(req.task, lambda: ts)
            except Exception as e:
                emit({"type": "error", "msg": str(e)})
            finally:
                _history.insert(0, {
                    "task_id": task_id,
                    "task": req.task,
                    "workspace": ws,
                    "outcome": result.outcome if result else "error",
                    "steps": len(result.steps) if result else 0,
                    "timestamp": ts,
                })
                # 只保留最近 100 条
                if len(_history) > 100:
                    _history.pop()
                emit({"type": "loop_stopped", "outcome": result.outcome if result else "error"})

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        tasks_state[task_id] = {
            "loop": agent, "queue": queue, "events": events_log, "thread": thread,
        }
        return {"task_id": task_id}

    @app.get("/api/tasks/{task_id}/events")
    async def events(task_id: str):
        entry = tasks_state.get(task_id)
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
        entry = tasks_state.get(task_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown task_id")
        entry["loop"].approve(aid, req.decision)
        return {"ok": True, "approved": req.decision}

    @app.get("/api/tasks/{task_id}/pending")
    def pending(task_id: str):
        entry = tasks_state.get(task_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown task_id")
        snap = entry["loop"].current_pending()
        if not snap:
            return {"pending": False}
        return {"pending": True, **snap}

    # ── 任务历史 ──
    @app.get("/api/tasks")
    def list_tasks():
        return {"tasks": _history}

    # ── 工作区文件树 ──
    @app.get("/api/workspace/tree")
    def workspace_tree():
        root = Path(_workspace["path"]).resolve()
        if not root.exists():
            root.mkdir(parents=True, exist_ok=True)
        return _build_file_tree(root)

    @app.get("/api/workspace/file")
    def workspace_file(path: str = Query(...)):
        """读取工作区内文件内容(安全围栏:禁止越界)。"""
        root = Path(_workspace["path"]).resolve()
        target = (root / path).resolve()
        if not str(target).startswith(str(root)):
            raise HTTPException(status_code=403, detail="越界访问")
        if not target.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        if not target.is_file():
            raise HTTPException(status_code=400, detail="不是文件")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = f"[二进制文件,{target.stat().st_size} 字节]"
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"path": str(path), "content": content, "size": target.stat().st_size}

    # ── 配置与信息 ──
    @app.get("/api/config")
    def config_info():
        """返回当前配置(不含敏感信息)。"""
        cred_info = creds.info()
        return {
            "mode": "mock" if _mode["mock"] else "real",
            "workspace": _workspace["path"],
            "model": cred_info.get("model", "") or "(未配置)",
            "models_available": _KNOWN_MODELS,
            "llm_configured": cred_info.get("configured", False),
            "base_url": cred_info.get("base_url", ""),
        }

    @app.post("/api/config/model")
    def switch_model(req: ModelSwitchReq):
        """切换 LLM 模型(更新 keychain 中存储的 model)。"""
        creds.set_model(req.model)
        return {"model": req.model, "ok": True}

    @app.post("/api/config/workspace")
    def switch_workspace(req: WorkspaceSwitchReq):
        """切换工作区目录。"""
        new_root = Path(req.workspace).resolve()
        if not new_root.exists():
            new_root.mkdir(parents=True, exist_ok=True)
        _workspace["path"] = str(new_root)
        return {"workspace": str(new_root), "ok": True}

    @app.post("/api/config/mode")
    def switch_mode(req: ModeSwitchReq):
        """切换 mock/real 模式。"""
        mode = req.mode
        if mode not in ("mock", "real"):
            raise HTTPException(status_code=400, detail="mode 必须为 mock 或 real")
        _mode["mock"] = mode == "mock"
        return {"mode": mode, "ok": True}

    # ── 凭据管理 ──
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


def _default_config(project_root: str) -> Config:
    """无 config.yaml 时用最小默认(project_root + llm 占位);其余取 dataclass 默认。"""
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    try:
        yaml.safe_dump(
            {"project_root": str(project_root), "llm": {"base_url": "x", "model": "m"}},
            f,
        )
        f.close()
        return load_config(f.name)
    finally:
        try:
            Path(f.name).unlink()
        except OSError:
            pass


def _demo_script():
    """WebUI 演示脚本:红→绿。"""
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
