"""§A.6 演示 ③:连续同类失败触发策略切换并按停机条件停。"""
from coding_agent_harness.core.loop import AgentLoop
from coding_agent_harness.llm.mock import MockLLMClient
from coding_agent_harness.memory.store import Memory
from coding_agent_harness.config import load_config
from coding_agent_harness.models import WriteFile, RunTests
import yaml, tempfile, shutil
from pathlib import Path

FIX = Path(__file__).parent.parent.parent / "fixtures" / "sample_pkg"


def _cfg(root):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump({"project_root": str(root), "llm": {"base_url": "x", "model": "m"},
        "guardrails": {"max_rounds": 8, "same_category_prompt_at": 2,
                        "same_category_stop_at": 4, "no_change_stop_at": 3},
        "feedback": {"pytest_args": ["--tb=short", "-q"], "max_traceback_excerpt_lines": 8}},
        f); f.close()
    return load_config(f.name)


class _CapturingClient:
    """包装 MockLLMClient,记录每次收到的 messages,用于断言策略提示被注入。"""
    def __init__(self, script):
        self._inner = MockLLMClient(script)
        self.received = []
    def complete(self, messages, tools, state):
        self.received.append([m.content for m in messages])
        return self._inner.complete(messages, tools, state)


def test_repeated_failure_triggers_prompt_and_stop(tmp_path):
    shutil.copytree(FIX, tmp_path / "ws", dirs_exist_ok=True)
    ws = tmp_path / "ws"
    # round1 错值 → round2 FAIL(same_cat=1,no_change=1)→ round3 同一错值 →
    # round4 FAIL(same_cat=2,no_change=2,注入"换思路",不停)→ round5 消息含"换思路"
    # 并 FAIL(same_cat=3,no_change=3 → stuck)。prompt 在停机前已送达 LLM。
    mock = _CapturingClient([
        {"when": "round 1", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+2\n"), "intent": "修1"},
        {"when": "round 2", "action": RunTests(), "intent": "跑"},
        {"when": "round 3", "action": WriteFile("calc.py", "def add(a,b):\n    return a+b+2\n"), "intent": "再修还是错"},
        {"when": "always", "action": RunTests(), "intent": "跑"},
    ])
    cfg = _cfg(ws)
    mem = Memory(str(ws / "fixes.json"), str(ws / "conv.json"), 3)
    loop = AgentLoop(llm=mock, config=cfg, memory=mem)
    result = loop.run(task="修", ts_provider=lambda: "2026-07-22T00:00:00")
    assert result.outcome == "stuck"
    assert result.steps  # 有步骤
    # 策略提示真被注入:某轮收到的 messages 含"换思路"
    flat = "\n".join("\n".join(c) for c in mock.received)
    assert "换思路" in flat, "连续同类失败应注入换思路策略提示"
