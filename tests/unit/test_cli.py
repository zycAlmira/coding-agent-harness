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





def test_chat_uses_cwd_as_workdir(monkeypatch, capsys, tmp_path):
    """chat 默认用当前终端目录(cwd)作为工作目录,像 Claude Code 一样——
    在哪个文件夹打开终端就以它为项目根(覆盖 config.yaml 的 project_root)。"""
    import builtins
    from coding_agent_harness.main import main
    (tmp_path / "config.yaml").write_text(
        "project_root: /nonexistent\nllm: {base_url: x, model: m}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # 捕获传给 AgentLoop 的 config,验证 project_root 被 cwd 覆盖
    captured = {}
    real_init = __import__("coding_agent_harness.core.loop", fromlist=["AgentLoop"]).AgentLoop.__init__
    def fake_init(self, llm, config, memory, **kw):
        captured["project_root"] = str(config.project_root)
        return real_init(self, llm=llm, config=config, memory=memory, **kw)
    monkeypatch.setattr("coding_agent_harness.core.loop.AgentLoop.__init__", fake_init)
    # 模拟输入:exit
    monkeypatch.setattr(builtins, "input", lambda *a: "exit")
    # 缺 creds 会抛,但验证 project_root 先被设置
    try:
        main(["chat"])
    except Exception:
        pass
    assert captured.get("project_root") == str(tmp_path), \
        f"chat 应用 cwd 作为工作目录: {captured.get('project_root')} != {tmp_path}"


def test_chat_no_config_uses_defaults(monkeypatch, capsys, tmp_path):
    """chat 无 config.yaml 时自动用默认配置(不报错,开箱即用):
    默认 base_url/model + 当前目录作工作目录。"""
    import builtins
    from coding_agent_harness.main import main
    monkeypatch.chdir(tmp_path)  # 无 config.yaml
    captured = {}
    real_init = __import__("coding_agent_harness.core.loop", fromlist=["AgentLoop"]).AgentLoop.__init__
    def fake_init(self, llm, config, memory, **kw):
        captured["project_root"] = str(config.project_root)
        captured["base_url"] = config.llm.base_url
        captured["model"] = config.llm.model
        return real_init(self, llm=llm, config=config, memory=memory, **kw)
    monkeypatch.setattr("coding_agent_harness.core.loop.AgentLoop.__init__", fake_init)
    monkeypatch.setattr(builtins, "input", lambda *a: "exit")
    try:
        main(["chat"])
    except Exception:
        pass
    assert captured.get("project_root") == str(tmp_path), "无 config 时用当前目录"
    assert captured.get("model"), "无 config 时用默认 model"


def test_render_md_plain_text():
    """纯文本原样返回(无 markdown 符号)。"""
    from coding_agent_harness.main import _render_md
    assert _render_md("你好") == "你好"


def test_render_md_heading_list_code():
    """标题/列表/代码块转终端友好格式:去符号、加缩进/前缀。"""
    from coding_agent_harness.main import _render_md
    md = "## 文件清单\n- calc.py\n- README.md\n\n```python\ndef add(a,b):\n    return a+b\n```"
    out = _render_md(md)
    assert "##" not in out, "标题符号应去除"
    assert "文件清单" in out
    assert "• calc.py" in out or "- calc.py" in out, "列表应有前缀"
    assert "```" not in out, "代码块围栏应去除"
    assert "def add(a,b)" in out


def test_render_md_inline():
    """行内代码/加粗/斜体符号去除,保留内容。"""
    from coding_agent_harness.main import _render_md
    out = _render_md("运行 **pytest** 看 `test_calc.py` 结果 *注意*")
    assert "**" not in out and "`" not in out and "*" not in out.replace("注意", "")
    assert "pytest" in out and "test_calc.py" in out


def test_chat_hitl_enabled(monkeypatch, capsys, tmp_path):
    """chat 应启用 HITL(hitl_enabled=True),危险动作可在终端审批。"""
    import builtins
    from coding_agent_harness.main import main
    monkeypatch.chdir(tmp_path)  # 无 config,用默认
    captured = {}
    real_init = __import__("coding_agent_harness.core.loop", fromlist=["AgentLoop"]).AgentLoop.__init__
    def fake_init(self, llm, config, memory, **kw):
        captured["hitl"] = kw.get("hitl_enabled", False)
        return real_init(self, llm=llm, config=config, memory=memory, **kw)
    monkeypatch.setattr("coding_agent_harness.core.loop.AgentLoop.__init__", fake_init)
    monkeypatch.setattr(builtins, "input", lambda *a: "exit")
    try:
        main(["chat"])
    except Exception:
        pass
    assert captured.get("hitl") is True, f"chat 应启用 HITL: {captured}"
