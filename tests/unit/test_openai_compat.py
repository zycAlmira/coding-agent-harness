from coding_agent_harness.llm.openai_compat import OpenAICompatibleClient, parse_tool_call
from coding_agent_harness.models import WriteFile


def test_parse_tool_call_to_action():
    tc = {"name": "write_file", "arguments": {"path": "a.py", "content": "x"}}
    action, intent = parse_tool_call(tc)
    assert isinstance(action, WriteFile)
    assert action.path == "a.py"
    assert intent  # intent 来自 arguments.get('intent') 或默认


def test_client_uses_creds(monkeypatch):
    class FakeCreds:
        def get(self): return ("sk-x", "http://api", "m")
    calls = {}
    def fake_post(url, *, headers, json, timeout=None):
        calls["url"] = url
        calls["headers"] = headers
        calls["json"] = json
        class R:
            status_code = 200
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")
            def json(self):
                return {
                    "choices": [
                        {"message": {"tool_calls": [
                            {"function": {"name": "stop",
                             "arguments": {"reason": "done", "intent": "完成"}}}
                        ]}}
                    ]
                }
        return R()
    import coding_agent_harness.llm.openai_compat as mod
    monkeypatch.setattr(mod.httpx, "post", fake_post, raising=True)
    c = OpenAICompatibleClient(FakeCreds())
    t = c.complete([], [], None)
    assert t.intent == "完成"
    assert "sk-x" not in str(calls["json"])  # key 不进请求体(只进 header)
    assert calls["headers"]["Authorization"] == "Bearer sk-x"  # 但进 header(正常)
