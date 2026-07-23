import threading
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


def _run_in_thread(loop, task):
    box = {}
    def worker():
        box["r"] = loop.run(task, ts_provider=lambda: "2026-07-22T00:00:00")
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t, box


def test_hitl_approve_then_execute(tmp_path):
    shutil.copytree(FIX, tmp_path / "ws", dirs_exist_ok=True)
    ws = tmp_path / "ws"
    assert (ws / "calc.py").exists()
    mock = MockLLMClient([
        {"when": "round 1", "action": DeleteFile("calc.py"), "intent": "删 calc.py"},
        {"when": "always", "action": Stop("done"), "intent": "完成"},
    ])
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    loop = AgentLoop(llm=mock, config=cfg, memory=mem, hitl_enabled=True)
    t, box = _run_in_thread(loop, "删 calc.py")
    aid = loop.wait_for_pending_approval(timeout=5)
    assert aid is not None
    loop.approve(aid, True)
    t.join(timeout=5)
    assert not (ws / "calc.py").exists()       # 审批通过 → 真删
    assert box["r"].outcome == "stopped"        # 随后 Stop


def test_hitl_reject_keeps_file(tmp_path):
    shutil.copytree(FIX, tmp_path / "ws", dirs_exist_ok=True)
    ws = tmp_path / "ws"
    mock = MockLLMClient([
        {"when": "round 1", "action": DeleteFile("calc.py"), "intent": "删 calc.py"},
        {"when": "always", "action": Stop("done"), "intent": "完成"},
    ])
    cfg = _cfg(ws)
    mem = Memory(cfg.memory.fixes_path, cfg.memory.conventions_path, cfg.memory.retrieve_top_k)
    loop = AgentLoop(llm=mock, config=cfg, memory=mem, hitl_enabled=True)
    t, box = _run_in_thread(loop, "删 calc.py")
    aid = loop.wait_for_pending_approval(timeout=5)
    assert aid is not None
    loop.approve(aid, False)
    t.join(timeout=5)
    assert (ws / "calc.py").exists()            # 被拒 → 不删
    assert box["r"].outcome == "stopped"


def test_approve_unknown_id_raises():
    loop = AgentLoop(llm=None, config=None, memory=None, hitl_enabled=True)
    try:
        loop.approve("nope", True)
        assert False, "应抛 KeyError"
    except KeyError:
        pass
