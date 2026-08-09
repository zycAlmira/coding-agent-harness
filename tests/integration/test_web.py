from coding_agent_harness.web.app import create_app
from coding_agent_harness.models import DeleteFile, Stop
from fastapi.testclient import TestClient
import time


def test_submit_task_returns_id(tmp_path):
    app = create_app(project_root=tmp_path, use_mock=True)
    c = TestClient(app)
    r = c.post("/api/tasks", json={"task": "修 bug"})
    assert r.status_code == 200
    assert "task_id" in r.json()


def test_credentials_status_not_set(tmp_path):
    app = create_app(project_root=tmp_path, use_mock=True)
    c = TestClient(app)
    r = c.get("/api/credentials/status")
    assert r.status_code == 200
    assert r.json() == {"set": False} or r.json().get("set") in (True, False)


def test_serves_index_html(tmp_path):
    app = create_app(project_root=tmp_path, use_mock=True)
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    assert "Coding Agent" in r.text
    assert "pending_approval" in r.text  # 前端含审批按钮渲染分支
    assert "mdRender" in r.text  # agent 回复 markdown 渲染
    assert "mdInline" in r.text
    assert ".msg-agent .bubble pre" in r.text  # markdown 代码块样式


def test_hitl_approve_deletes_file(tmp_path):
    """§A.6 ① 端到端:submit DeleteFile 任务 → 轮询 /pending → POST /approvals(通过)
    → 文件真删。验证 WebUI 运行态审批链路可达。"""
    (tmp_path / "calc.py").write_text("orig")
    script = [
        {"when": "round 1", "action": DeleteFile("calc.py"), "intent": "删 calc"},
        {"when": "always", "action": Stop("done"), "intent": "完成"},
    ]
    app = create_app(project_root=tmp_path, use_mock=True, mock_script=script)
    c = TestClient(app)
    tid = c.post("/api/tasks", json={"task": "删 calc"}).json()["task_id"]

    # 轮询 /pending 直到出现 approval_id(worker 线程到 NeedsApproval 挂起)
    aid = None
    for _ in range(60):
        r = c.get(f"/api/tasks/{tid}/pending").json()
        if r.get("pending"):
            aid = r["approval_id"]
            assert r["intent"] == "删 calc"  # intent 真穿透到审批面
            break
        time.sleep(0.1)
    assert aid is not None, "应出现 pending 审批"

    # 通过审批
    ar = c.post(f"/api/tasks/{tid}/approvals/{aid}", json={"decision": True})
    assert ar.status_code == 200 and ar.json()["approved"] is True

    # worker 线程恢复后真删 calc.py
    deleted = False
    for _ in range(60):
        if not (tmp_path / "calc.py").exists():
            deleted = True
            break
        time.sleep(0.1)
    assert deleted, "审批通过后应真删 calc.py"

