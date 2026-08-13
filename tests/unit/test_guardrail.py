from coding_agent_harness.config import load_config
from coding_agent_harness.models import (
    WriteFile, DeleteFile, RunShell, ReadFile, RunTests, ListDir, Stop,
    Allow, Deny, NeedsApproval,
)
from coding_agent_harness.guardrails.guardrail import guardrail
import yaml
import tempfile


def _cfg(blacklist=None, whitelist=None, root="."):
    raw = {
        "project_root": root,
        "llm": {"base_url": "x", "model": "m"},
        "guardrails": {
            "shell_blacklist": blacklist or ["rm -rf"],
            # None → 不写该键,取 config 默认白名单(扩展后的多语言构建命令)
            **({"shell_whitelist": whitelist} if whitelist is not None else {}),
        },
    }
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump(raw, f)
    f.close()
    return load_config(f.name)


def test_delete_needs_approval():
    assert isinstance(guardrail(DeleteFile("a.py"), _cfg()), NeedsApproval)


def test_write_inside_project_allowed(tmp_path):
    cfg = _cfg(root=str(tmp_path))
    assert isinstance(guardrail(WriteFile("src/a.py", "x"), cfg), Allow)


def test_write_outside_project_needs_approval(tmp_path):
    cfg = _cfg(root=str(tmp_path))
    # 用 ../ 逃逸
    assert isinstance(guardrail(WriteFile("../outside.txt", "x"), cfg), NeedsApproval)


def test_shell_blacklist_denied():
    assert isinstance(guardrail(RunShell("rm -rf /"), _cfg()), Deny)


def test_shell_whitelist_allowed():
    assert isinstance(guardrail(RunShell("pytest -q"), _cfg()), Allow)


def test_whitelist_not_bypassed_by_substring():
    # `pytest_evil --delete` 含子串 `pytest`,但首词不是 pytest,不得 Allow
    assert isinstance(guardrail(RunShell("pytest_evil --delete"), _cfg()), NeedsApproval)


def test_whitelist_first_token_match():
    # 首词精确匹配仍 Allow,带参数/路径不影响
    assert isinstance(guardrail(RunShell("pytest tests/ -v"), _cfg()), Allow)


def test_shell_unknown_needs_approval():
    assert isinstance(guardrail(RunShell("make build"), _cfg()), NeedsApproval)


def test_read_and_tests_and_stop_allowed():
    cfg = _cfg()
    assert isinstance(guardrail(ReadFile("a.py"), cfg), Allow)
    assert isinstance(guardrail(RunTests(), cfg), Allow)
    assert isinstance(guardrail(Stop("done"), cfg), Allow)
    assert isinstance(guardrail(ListDir("."), cfg), Allow)


def test_whitelist_multi_language_build():
    """白名单扩展:Java/Node/Go 构建命令可执行(agent 自主组织多语言构建)。"""
    for cmd in ["mvn test", "mvn -q compile", "gradle test", "javac -version",
                "npm test", "npm run build", "node script.js", "yarn test",
                "go test ./...", "go build", "git status", "git diff"]:
        assert isinstance(guardrail(RunShell(cmd), _cfg()), Allow), f"{cmd} 应放行"


def test_whitelist_dangerous_still_denied():
    """危险命令仍被黑名单拦截,白名单扩展不削弱安全。"""
    for cmd in ["rm -rf /", "mvn test && rm -rf /", "sudo rm -rf"]:
        assert isinstance(guardrail(RunShell(cmd), _cfg()), Deny), f"{cmd} 应拦截"
