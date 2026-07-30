"""FastAPI 单页 WebUI。对话式 SSE 推送,HITL 审批,凭据管理,对话持久化。"""
from __future__ import annotations
import asyncio
import json
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from coding_agent_harness.config import Config, load_config
from coding_agent_harness.core.loop import AgentLoop
from coding_agent_harness.llm.base import Message
from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.memory.store import Memory
from coding_agent_harness.creds.keychain import Creds


# ── 请求模型 ──
class TaskReq(BaseModel):
    task: str
    conversation_id: str | None = None  # 继续已有对话
    workspace: str | None = None


class ApproveReq(BaseModel):
    decision: bool


class CredSetReq(BaseModel):
    api_key: str
    base_url: str
    model: str


class ModelSwitchReq(BaseModel):
    model: str
    base_url: str | None = None  # 跨供应商切换时一并更新


class WorkspaceSwitchReq(BaseModel):
    workspace: str


class ModeSwitchReq(BaseModel):
    mode: str


# ── 对话数据模型 ──
@dataclass
class ConvTurn:
    """对话中的一轮:用户消息或 agent 执行结果。"""
    role: str  # "user" | "agent"
    content: str
    steps: list[dict] | None = None  # agent 的工具调用步骤
    outcome: str | None = None       # agent 轮的结局
    prior_history: list[dict] | None = None  # 序列化的 Message,供下一轮恢复上下文
    timestamp: str = ""


@dataclass
class Conversation:
    id: str
    title: str
    turns: list[ConvTurn] = field(default_factory=list)
    workspace: str = "./workspace"
    mode: str = "mock"
    created_at: str = ""
    updated_at: str = ""


# 对话持久化目录
_CONV_DIR = Path("./conversations")

# 已知模型列表(2026-07 最新)
_KNOWN_MODELS = [
    {
        "provider": "DeepSeek",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v3.2", "deepseek-chat"],
        "base_url": "https://api.deepseek.com/v1",
    },
    {
        "provider": "OpenAI",
        "models": ["gpt-5.6-sol", "gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "o3", "o4-mini"],
        "base_url": "https://api.openai.com/v1",
    },
    {
        "provider": "Anthropic Claude",
        "models": ["claude-fable-5", "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
        "base_url": "https://api.anthropic.com/v1",
    },
    {
        "provider": "Google Gemini",
        "models": ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview"],
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
    },
    {
        "provider": "通义千问 Qwen",
        "models": ["qwen3.8-max-preview", "qwen3.7-max", "qwen3.7-plus", "qwen3.7-flash"],
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    {
        "provider": "智谱 GLM",
        "models": ["glm-5.2", "glm-5.1", "glm-5"],
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
    },
]


def _conv_path(conv_id: str) -> Path:
    return _CONV_DIR / f"{conv_id}.json"


def _save_conv(conv: Conversation) -> None:
    _CONV_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "id": conv.id,
        "title": conv.title,
        "turns": [
            {
                "role": t.role,
                "content": t.content,
                "steps": t.steps,
                "outcome": t.outcome,
                "prior_history": t.prior_history,
                "timestamp": t.timestamp,
            }
            for t in conv.turns
        ],
        "workspace": conv.workspace,
        "mode": conv.mode,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
    }
    _conv_path(conv.id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_conv(conv_id: str) -> Conversation | None:
    p = _conv_path(conv_id)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return Conversation(
        id=data["id"],
        title=data["title"],
        turns=[ConvTurn(**t) for t in data.get("turns", [])],
        workspace=data.get("workspace", "./workspace"),
        mode=data.get("mode", "mock"),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


def _list_convs() -> list[dict]:
    """列出所有已保存对话(摘要,不含完整 turns)。"""
    if not _CONV_DIR.exists():
        return []
    result = []
    for p in sorted(_CONV_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            result.append({
                "id": data["id"],
                "title": data.get("title", ""),
                "turn_count": len(data.get("turns", [])),
                "workspace": data.get("workspace", ""),
                "mode": data.get("mode", ""),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return result


def _serialize_messages(msgs: list[Message]) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in msgs]


def _deserialize_messages(data: list[dict] | None) -> list[Message]:
    if not data:
        return []
    return [Message(role=d["role"], content=d["content"]) for d in data]


def _build_file_tree(root: Path, rel: Path | None = None, depth: int = 0) -> dict:
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
            if entry.name in ("__pycache__", "node_modules", ".venv", "venv", ".git", "dist", ".pytest_cache", ".ruff_cache", ".mypy_cache"):
                continue
            if entry.is_dir():
                child = _build_file_tree(root, rel / entry.name, depth + 1)
                children.append(child)
            elif entry.is_file():
                # 所有文件都展示,前端用 emoji 区分类型
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
    creds = Creds()
    _workspace: dict[str, str] = {"path": str(project_root)}
    _mode: dict[str, bool] = {"mock": use_mock}
    # 活跃对话:conv_id → {loop, queue, events_log, thread, conversation}
    _active: dict[str, dict] = {}

    if config is None:
        config = _default_config(str(project_root))

    @app.get("/")
    def index():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    # ═══════════════════════════════════════════
    # 对话 API
    # ═══════════════════════════════════════════

    @app.get("/api/conversations")
    def list_conversations():
        return {"conversations": _list_convs()}

    @app.get("/api/conversations/{conv_id}")
    def get_conversation(conv_id: str):
        conv = _load_conv(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="对话不存在")
        return {
            "id": conv.id, "title": conv.title,
            "turns": [
                {
                    "role": t.role, "content": t.content,
                    "steps": t.steps, "outcome": t.outcome,
                    "timestamp": t.timestamp,
                }
                for t in conv.turns
            ],
            "workspace": conv.workspace, "mode": conv.mode,
            "created_at": conv.created_at, "updated_at": conv.updated_at,
        }

    @app.delete("/api/conversations/{conv_id}")
    def delete_conversation(conv_id: str):
        p = _conv_path(conv_id)
        if p.exists():
            p.unlink()
        return {"ok": True}

    @app.post("/api/conversations/{conv_id}/messages")
    async def send_message(conv_id: str, req: TaskReq):
        """向已有对话发送新消息,继续多轮对话。"""
        conv = _load_conv(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="对话不存在")

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(e: dict) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, e)
            except RuntimeError:
                pass

        # 从最后一轮的 prior_history 恢复上下文
        prior_history = None
        if conv.turns:
            last = conv.turns[-1]
            prior_history = _deserialize_messages(last.prior_history)

        ws = conv.workspace
        cfg = _default_config(ws)
        mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
        llm = (
            MockLLMClient(mock_script if mock_script is not None else _demo_script())
            if _mode["mock"]
            else _real_llm(creds)
        )
        agent = AgentLoop(llm=llm, config=cfg, memory=mem, on_event=emit, hitl_enabled=True)

        # 收集本轮事件(供存储)
        events_log: list[dict] = []

        def emit_and_log(e: dict) -> None:
            events_log.append(e)
            emit(e)

        # 重新绑定 on_event
        agent.on_event = emit_and_log

        ts = datetime.now(timezone.utc).isoformat()

        def worker():
            # 添加用户消息到对话
            conv.turns.append(ConvTurn(
                role="user", content=req.task, timestamp=ts,
            ))
            outcome = "error"
            try:
                result = agent.run(req.task, lambda: ts, prior_history=prior_history)
                outcome = result.outcome
            except Exception as e:
                emit_and_log({"type": "error", "msg": str(e)})
            finally:
                # 收集本轮 agent 的 conversation_history 供下一轮恢复
                ch = _serialize_messages(agent.conversation_history)
                conv.turns.append(ConvTurn(
                    role="agent",
                    content=_extract_agent_text(events_log),
                    steps=[e for e in events_log if e.get("type") not in ("response", "loop_stopped", "error")],
                    outcome=outcome,
                    prior_history=ch,
                    timestamp=ts,
                ))
                conv.updated_at = ts
                _save_conv(conv)
                emit_and_log({"type": "loop_stopped", "outcome": outcome})

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        _active[conv_id] = {"loop": agent, "queue": queue, "events_log": events_log, "thread": thread}
        return {"conversation_id": conv_id}

    # ═══════════════════════════════════════════
    # 任务提交(创建新对话或继续已有)
    # ═══════════════════════════════════════════

    @app.post("/api/tasks")
    async def submit(req: TaskReq):
        """创建新对话或继续已有对话。"""
        ts = datetime.now(timezone.utc).isoformat()

        # 确定是新对话还是继续已有
        if req.conversation_id:
            conv = _load_conv(req.conversation_id)
            if not conv:
                raise HTTPException(status_code=404, detail="对话不存在")
        else:
            conv_id = uuid.uuid4().hex[:12]
            ws = req.workspace or _workspace["path"]
            title = req.task[:80] + ("…" if len(req.task) > 80 else "")
            conv = Conversation(
                id=conv_id, title=title,
                workspace=ws, mode="mock" if _mode["mock"] else "real",
                created_at=ts, updated_at=ts,
            )

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        events_log: list[dict] = []

        def emit(e: dict) -> None:
            events_log.append(e)
            try:
                loop.call_soon_threadsafe(queue.put_nowait, e)
            except RuntimeError:
                pass

        # 从对话最后一轮的 prior_history 恢复上下文
        prior_history = None
        if conv.turns:
            last_agent_turn = None
            for t in reversed(conv.turns):
                if t.role == "agent" and t.prior_history:
                    last_agent_turn = t
                    break
            if last_agent_turn:
                prior_history = _deserialize_messages(last_agent_turn.prior_history)

        ws = conv.workspace
        cfg = _default_config(ws)
        mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
        llm = (
            MockLLMClient(mock_script if mock_script is not None else _demo_script())
            if _mode["mock"]
            else _real_llm(creds)
        )
        agent = AgentLoop(llm=llm, config=cfg, memory=mem, on_event=emit, hitl_enabled=True)

        # 添加用户消息
        conv.turns.append(ConvTurn(role="user", content=req.task, timestamp=ts))

        def worker():
            outcome = "error"
            try:
                result = agent.run(req.task, lambda: ts, prior_history=prior_history)
                outcome = result.outcome
            except Exception as e:
                emit({"type": "error", "msg": str(e)})
            finally:
                ch = _serialize_messages(agent.conversation_history)
                conv.turns.append(ConvTurn(
                    role="agent",
                    content=_extract_agent_text(events_log),
                    steps=[e for e in events_log if e.get("type") not in ("response", "loop_stopped", "error")],
                    outcome=outcome,
                    prior_history=ch,
                    timestamp=ts,
                ))
                conv.updated_at = ts
                _save_conv(conv)
                emit({"type": "loop_stopped", "outcome": outcome})

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        _active[conv.id] = {"loop": agent, "queue": queue, "events_log": events_log, "thread": thread}
        return {"conversation_id": conv.id, "task_id": conv.id}

    # ═══════════════════════════════════════════
    # SSE 事件流
    # ═══════════════════════════════════════════

    @app.get("/api/tasks/{conv_id}/events")
    async def events(conv_id: str):
        entry = _active.get(conv_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown id")

        async def stream():
            q = entry["queue"]
            while True:
                e = await q.get()
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
                if e.get("type") == "loop_stopped":
                    break
        return StreamingResponse(stream(), media_type="text/event-stream")

    # ═══════════════════════════════════════════
    # HITL 审批
    # ═══════════════════════════════════════════

    @app.post("/api/tasks/{conv_id}/approvals/{aid}")
    def approve(conv_id: str, aid: str, req: ApproveReq):
        entry = _active.get(conv_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown id")
        entry["loop"].approve(aid, req.decision)
        return {"ok": True, "approved": req.decision}

    @app.get("/api/tasks/{conv_id}/pending")
    def pending(conv_id: str):
        entry = _active.get(conv_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown id")
        snap = entry["loop"].current_pending()
        if not snap:
            return {"pending": False}
        return {"pending": True, **snap}

    # ═══════════════════════════════════════════
    # 工作区文件浏览
    # ═══════════════════════════════════════════

    @app.post("/api/workspace/picker")
    def workspace_picker():
        """打开系统原生文件夹选择器(macOS 访达/Win 资源管理器),返回所选路径。"""
        import platform
        import subprocess
        system = platform.system()
        try:
            if system == "Darwin":
                # macOS: 用 AppleScript 调用访达选择文件夹
                script = (
                    'set folderPath to choose folder with prompt "选择工作目录"\n'
                    'return POSIX path of folderPath'
                )
                proc = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True, text=True, timeout=120,
                )
                if proc.returncode != 0:
                    detail = proc.stderr.strip() or "用户取消选择"
                    raise HTTPException(status_code=400, detail=detail)
                path = proc.stdout.strip().rstrip("/")
                if not path:
                    raise HTTPException(status_code=400, detail="未选择文件夹")
            elif system == "Windows":
                # Windows: PowerShell FolderBrowserDialog
                ps_script = (
                    'Add-Type -AssemblyName System.Windows.Forms\n'
                    '$f = New-Object System.Windows.Forms.FolderBrowserDialog\n'
                    '$f.Description = "选择工作目录"\n'
                    'if ($f.ShowDialog() -eq "OK") { $f.SelectedPath }'
                )
                proc = subprocess.run(
                    ["powershell", "-Command", ps_script],
                    capture_output=True, text=True, timeout=120,
                )
                if proc.returncode != 0:
                    raise HTTPException(status_code=400, detail=proc.stderr.strip() or "用户取消选择")
                path = proc.stdout.strip()
                if not path:
                    raise HTTPException(status_code=400, detail="未选择文件夹")
            else:
                # Linux: 尝试 zenity, 无 GUI 则回退
                proc = subprocess.run(
                    ["zenity", "--file-selection", "--directory", "--title=选择工作目录"],
                    capture_output=True, text=True, timeout=120,
                )
                if proc.returncode != 0:
                    raise HTTPException(status_code=400, detail="用户取消选择或无图形界面(请手动输入路径)")
                path = proc.stdout.strip()

            # 更新当前工作区
            _workspace["path"] = path
            return {"path": path, "ok": True}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/workspace/tree")
    def workspace_tree():
        root = Path(_workspace["path"]).resolve()
        if not root.exists():
            root.mkdir(parents=True, exist_ok=True)
        return _build_file_tree(root)

    @app.get("/api/workspace/file")
    def workspace_file(path: str = Query(...)):
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

    # ═══════════════════════════════════════════
    # 配置与凭据
    # ═══════════════════════════════════════════

    @app.get("/api/config")
    def config_info():
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
        """切换 LLM 模型(更新 keychain 中的 model 和可选 base_url)。"""
        creds.set_model(req.model, base_url=req.base_url)
        return {"model": req.model, "ok": True}

    @app.post("/api/config/workspace")
    def switch_workspace(req: WorkspaceSwitchReq):
        new_root = Path(req.workspace).resolve()
        if not new_root.exists():
            new_root.mkdir(parents=True, exist_ok=True)
        _workspace["path"] = str(new_root)
        return {"workspace": str(new_root), "ok": True}

    @app.post("/api/config/mode")
    def switch_mode(req: ModeSwitchReq):
        if req.mode not in ("mock", "real"):
            raise HTTPException(status_code=400, detail="mode 必须为 mock 或 real")
        _mode["mock"] = req.mode == "mock"
        return {"mode": req.mode, "ok": True}

    @app.get("/api/credentials/status")
    def cred_status():
        return creds.status()

    @app.post("/api/credentials/set")
    def cred_set(req: CredSetReq):
        creds.set(req.api_key, req.base_url, req.model)
        return {"set": True}

    # ── 静态文件 ──
    static = Path(__file__).parent / "static"
    static.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=static), name="static")
    return app


def _extract_agent_text(events: list[dict]) -> str:
    """从事件列表中提取 agent 的纯文本回复(合并所有 response 事件)。"""
    parts = []
    for e in events:
        if e.get("type") == "response":
            parts.append(e.get("text", ""))
    return "\n\n".join(parts) if parts else ""


def _default_config(project_root: str) -> Config:
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
    from coding_agent_harness.models import WriteFile, RunTests, Stop
    return [
        {"when": "round 1", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+2\n"), "intent": "我先改返回值"},
        {"when": "round 2", "action": RunTests(), "intent": "验证修复"},
        {"when": "round 4", "action": RunTests(), "intent": "再验证"},
        {"when": "feedback.category == AssertionFailure", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+1\n"), "intent": "上次断言失败,改 off-by-one"},
        {"when": "feedback.status == PASS", "action": Stop("修复完成:将 calc.py 中 add 函数的返回值从 a+b+2 改为 a+b+1,使得 add(2,2)=5 通过测试断言。1 个测试全部通过。"), "intent": "总结并停止"},
    ]


def _real_llm(creds):
    from coding_agent_harness.llm.openai_compat import OpenAICompatibleClient
    return OpenAICompatibleClient(creds)
