"""§A.6 演示 ②:注入失败 → 反馈闭环改变下一步并红变绿。"""
from coding_agent_harness.core.loop import AgentLoop
from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.memory.store import Memory
from coding_agent_harness.config import load_config
from coding_agent_harness.models import WriteFile, RunTests, Stop
import yaml, tempfile, shutil
from pathlib import Path

FIX = Path(__file__).parent.parent.parent / "fixtures" / "sample_pkg"


def _cfg(root):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({"project_root": str(root), "llm": {"base_url": "x", "model": "m"},
        "guardrails": {"max_rounds": 8, "same_category_prompt_at": 2,
                        "same_category_stop_at": 3, "no_change_stop_at": 2},
        "feedback": {"pytest_args": ["--tb=short", "-q"], "max_traceback_excerpt_lines": 8}},
        f); f.close()
    return load_config(f.name)


def test_failure_feedback_changes_next_action(tmp_path):
    shutil.copytree(FIX, tmp_path / "ws", dirs_exist_ok=True)
    ws = tmp_path / "ws"
    # round1 写错值(a+b+2=6≠5)→ round2 FAIL(AssertionFailure)→ round3 据反馈写正确(a+b+1=5)
    # → round4 PASS。round4 须排在 feedback.category 前,否则被反馈分支抢占。
    mock = MockLLMClient([
        {"when": "round 1", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+2\n"), "intent": "我先改返回值"},
        {"when": "round 2", "action": RunTests(), "intent": "验证修复"},
        {"when": "round 4", "action": RunTests(), "intent": "再验证"},
        {"when": "feedback.category == AssertionFailure", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+1\n"), "intent": "上次断言失败,改 off-by-one"},
        {"when": "feedback.status == PASS", "action": Stop("done"), "intent": "测试全绿,完成"},
    ])
    cfg = _cfg(ws)
    mem = Memory(str(ws / "fixes.json"), str(ws / "conv.json"), 3)
    loop = AgentLoop(llm=mock, config=cfg, memory=mem)
    result = loop.run(task="修 add", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "success"
    pivot = [s for s in result.steps if s.turn and s.turn.intent == "上次断言失败,改 off-by-one"]
    assert pivot, "应存在因 AssertionFailure feedback 而改变动作的转折"
