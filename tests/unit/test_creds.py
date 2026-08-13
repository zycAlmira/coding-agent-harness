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


def test_creds_no_keyring_backend_fallback(monkeypatch):
    """容器无 keyring 后端(get_password 抛 NoKeyringError)→ 所有方法容错为未配置,不抛异常。"""
    import keyring
    from coding_agent_harness.creds.keychain import Creds
    def boom(*a, **k):
        raise keyring.errors.NoKeyringError("no backend")
    # 无后端时 get_keyring 返回 fail 后端,抛错的是 get_password/set_password 等
    monkeypatch.setattr("coding_agent_harness.creds.keychain.keyring.get_password", boom)
    monkeypatch.setattr("coding_agent_harness.creds.keychain.keyring.set_password", boom)
    monkeypatch.setattr("coding_agent_harness.creds.keychain.keyring.delete_password", boom)
    c = Creds()
    assert c.status() == {"set": False}
    assert c.info() == {"configured": False, "base_url": "", "model": ""}
    assert c.get() is None
    c.set("k", "u", "m")  # 不抛
    c.clear()  # 不抛
