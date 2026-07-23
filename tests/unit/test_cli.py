import keyring
import keyring.backend
import getpass
from coding_agent_harness.main import main


class _Mem(keyring.backend.KeyringBackend):
    priority = 10
    def __init__(self): self.d = {}
    def get_password(self, s, u): return self.d.get((s, u))
    def set_password(self, s, u, p): self.d[(s, u)] = p
    def delete_password(self, s, u): self.d.pop((s, u), None)


def _use_mem_keyring():
    keyring.set_keyring(_Mem())


def test_creds_status_not_set(capsys):
    _use_mem_keyring()
    rc = main(["creds", "status"])
    assert rc == 0
    assert "未设置" in capsys.readouterr().out


def test_unknown_command_errors(capsys):
    rc = main(["unknown"])
    assert rc != 0
    assert "未知命令" in capsys.readouterr().err


def test_creds_set_then_status(monkeypatch, capsys):
    _use_mem_keyring()
    monkeypatch.setattr(getpass, "getpass", lambda p="": "sk-test")
    answers = iter(["http://x", "m"])
    monkeypatch.setattr("builtins.input", lambda p="": next(answers))
    rc = main(["creds", "set"])
    assert rc == 0
    assert "已保存" in capsys.readouterr().out
    rc2 = main(["creds", "status"])
    assert rc2 == 0
    assert "已设置" in capsys.readouterr().out


def test_creds_clear(monkeypatch, capsys):
    _use_mem_keyring()
    monkeypatch.setattr(getpass, "getpass", lambda p="": "sk-test")
    answers = iter(["http://x", "m"])
    monkeypatch.setattr("builtins.input", lambda p="": next(answers))
    main(["creds", "set"])
    capsys.readouterr()
    rc = main(["creds", "clear"])
    assert rc == 0
    assert "已清除" in capsys.readouterr().out
    rc2 = main(["creds", "status"])
    assert rc2 == 0
    assert "未设置" in capsys.readouterr().out  # clear 后 status 显示未设置


def test_no_args_prints_usage(capsys):
    rc = main([])
    assert rc != 0
    assert "用法" in capsys.readouterr().err


def test_run_missing_config(monkeypatch, capsys, tmp_path):
    # run 子命令缺 config.yaml 时应友好报错 + rc=2,不抛 traceback
    monkeypatch.chdir(tmp_path)
    rc = main(["run", "do something"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "config.yaml" in err
