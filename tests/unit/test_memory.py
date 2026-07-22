import json
from pathlib import Path
from coding_agent_harness.memory.store import Memory, Fix
from coding_agent_harness.feedback.taxonomy import FailureCategory

FIX = Path(__file__).parent.parent / "fixtures" / "fixes.example.json"


def test_retrieve_by_category(tmp_path):
    f = tmp_path / "fixes.json"
    f.write_text(FIX.read_text())
    mem = Memory(f, tmp_path / "conv.json", top_k=3)
    out = mem.retrieve(FailureCategory.AssertionFailure)
    assert len(out) == 1
    assert out[0].fix == "修复 off-by-one"


def test_retrieve_unknown_category_empty(tmp_path):
    f = tmp_path / "fixes.json"
    f.write_text(FIX.read_text())
    mem = Memory(f, tmp_path / "conv.json", top_k=3)
    assert mem.retrieve(FailureCategory.Timeout) == []


def test_retrieve_respects_top_k(tmp_path):
    f = tmp_path / "fixes.json"
    data = [{"category": "AssertionFailure", "symptom": "s", "fix": f"f{i}", "timestamp": f"2026-07-22T0{i}"} for i in range(5)]
    f.write_text(json.dumps(data))
    mem = Memory(f, tmp_path / "conv.json", top_k=2)
    out = mem.retrieve(FailureCategory.AssertionFailure)
    assert len(out) == 2


def test_record_fix_appends(tmp_path):
    f = tmp_path / "fixes.json"
    f.write_text("[]")
    mem = Memory(f, tmp_path / "conv.json", top_k=3)
    mem.record_fix(Fix("AssertionFailure", "sym", "fixx", "2026-07-22T00:00:00"))
    data = json.loads(f.read_text())
    assert len(data) == 1 and data[0]["fix"] == "fixx"


def test_load_conventions(tmp_path):
    c = tmp_path / "conv.json"
    c.write_text(json.dumps([{"key": "style", "value": "snake_case"}]))
    mem = Memory(tmp_path / "f.json", c, top_k=3)
    convs = mem.load_conventions()
    assert "snake_case" in convs[0]
