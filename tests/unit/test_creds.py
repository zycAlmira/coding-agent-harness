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
