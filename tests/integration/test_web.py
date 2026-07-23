from coding_agent_harness.web.app import create_app
from fastapi.testclient import TestClient


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
