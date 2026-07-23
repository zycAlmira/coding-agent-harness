"""§A.6 演示 ①:治理护栏拦截危险动作(mock LLM)。"""
from coding_agent_harness.core.loop import AgentLoop
from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.memory.store import Memory
from coding_agent_harness.config import load_config
from coding_agent_harness.models import DeleteFile, Stop
import yaml
import tempfile
import shutil
from pathlib import Path

FIX = Path(__file__).parent.parent.parent / "fixtures" / "sample_pkg"


def _cfg(root):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({"project_root": str(root), "llm": {"base_url": "x", "model": "m"},
        "guardrails": {"max_rounds": 8, "same_category_prompt_at": 2,
                        "same_category_stop_at": 3, "no_change_stop_at": 2}},
        f)
    f.close()
    return load_config(f.name)


def test_guardrail_intercepts_delete_and_propagates_intent(tmp_path):
    shutil.copytree(FIX, tmp_path / "ws", dirs_exist_ok=True)
    ws = tmp_path / "ws"
    events = []
    mock = MockLLMClient([
        {"when": "round 1", "action": DeleteFile("calc.py"), "intent": "该文件被取代,删除以避免混淆"},
        {"when": "always", "action": Stop("done"), "intent": "结束"},
    ])
    cfg = _cfg(ws)
    mem = Memory(str(ws / "fixes.json"), str(ws / "conv.json"), 3)
    loop = AgentLoop(llm=mock, config=cfg, memory=mem, on_event=events.append)
    loop.run(task="删 calc", ts_provider=lambda: "2026-07-22T00:00:00")
    assert any(e["type"] == "guardrail_verdict" and e["verdict"] == "NeedsApproval" for e in events)
    assert events[0]["intent"] == "该文件被取代,删除以避免混淆"  # intent 随事件上送
    assert (ws / "calc.py").exists()  # 非 HITL 模式只回灌"需审批"字符串,没真删
