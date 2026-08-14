from coding_agent_harness.creds.keychain import Creds


def test_set_get_clear(monkeypatch):
    import keyring.backend
    class Mem(keyring.backend.KeyringBackend):
        priority = 10
        def __init__(self): self.d = {}
        def get_password(self, s, u): return self.d.get((s, u))
        def set_password(self, s, u, p): self.d[(s, u)] = p
        def delete_password(self, s, u):
            self.d.pop((s, u), None)
    keyring.set_keyring(Mem())
    c = Creds()
    assert c.status() == {"set": False}
    c.set(api_key="sk-x", base_url="http://x", model="m")
    assert c.status() == {"set": True}  # 不回显明文
    k, u, m = c.get()
    assert k == "sk-x" and u == "http://x" and m == "m"
    c.clear()
    assert c.status() == {"set": False}


def test_creds_no_keyring_backend_fallback(monkeypatch, tmp_path):
    """容器无 keyring 后端 → 回落文件后端(不再抛异常,set/get 可用)。"""
    import keyring
    from coding_agent_harness.creds.keychain import Creds
    def boom(*a, **k):
        raise keyring.errors.NoKeyringError("no backend")
    monkeypatch.setattr("coding_agent_harness.creds.keychain.keyring.get_password", boom)
    monkeypatch.setattr("coding_agent_harness.creds.keychain.keyring.set_password", boom)
    monkeypatch.setattr("coding_agent_harness.creds.keychain.keyring.delete_password", boom)
    monkeypatch.setenv("HARNESS_CREDS_FILE", str(tmp_path / "creds.json"))
    c = Creds()
    assert c.status() == {"set": False}
    c.set("k", "u", "m")  # 不抛,回落文件后端
    assert c.get() == ("k", "u", "m")
    assert c.status() == {"set": True}
    c.clear()  # 不抛


def test_creds_file_backend_fallback(monkeypatch, tmp_path):
    """keyring 无后端时回落文件后端:set/get/status/info 可用,权限 600。"""
    import keyring
    import os
    from coding_agent_harness.creds.keychain import Creds
    def boom(*a, **k):
        raise keyring.errors.NoKeyringError("no backend")
    monkeypatch.setattr("coding_agent_harness.creds.keychain.keyring.get_password", boom)
    monkeypatch.setattr("coding_agent_harness.creds.keychain.keyring.set_password", boom)
    monkeypatch.setattr("coding_agent_harness.creds.keychain.keyring.delete_password", boom)
    monkeypatch.setenv("HARNESS_CREDS_FILE", str(tmp_path / "creds.json"))
    c = Creds()
    c.set("sk-real-key", "https://api.deepseek.com/v1", "deepseek-chat")
    assert c.get() == ("sk-real-key", "https://api.deepseek.com/v1", "deepseek-chat")
    assert c.status() == {"set": True}
    info = c.info()
    assert info["configured"] and info["base_url"].startswith("https://")
    assert "sk-real-key" not in str(info)  # 不回显 key
    # 权限 600
    assert oct(os.stat(tmp_path / "creds.json").st_mode & 0o777) == "0o600"
    c.clear()
    assert c.status() == {"set": False}
