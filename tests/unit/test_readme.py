"""README 完整性单测(§五.4 必含章节 + §A.4 精神:交付文档也可验证)。

断言 README 存在且含必含章节(简介/安装/运行/分发/目录结构/安全边界)、
凭据安全配置(§3.2)、运行命令、docker/部署、安全边界关键词(护栏/HITL/mock/不硬编码)。
"""
from pathlib import Path

_RM = Path(__file__).resolve().parents[2] / "README.md"


def _txt() -> str:
    assert _RM.exists(), f"缺 {_RM}"
    return _RM.read_text()


def test_has_required_sections():
    txt = _txt()
    for h in ["## 简介", "## 安装", "## 运行", "## 分发", "## 目录结构", "## 安全边界"]:
        assert h in txt, f"README 缺章节:{h}"


def test_has_credential_section():
    # §3.2:key 安全配置方式
    assert "凭据" in _txt()
    assert "harness creds" in _txt()


def test_has_run_commands():
    txt = _txt()
    assert "harness serve" in txt
    assert "make test" in txt


def test_has_docker_and_deploy():
    txt = _txt()
    assert "docker build" in txt
    assert "fly" in txt.lower() or "deploy" in txt.lower()


def test_has_safety_boundary():
    # 安全边界必含(§五.4):护栏/HITL/mock/不硬编码 key
    txt = _txt()
    for kw in ["护栏", "HITL", "mock", "硬编码"]:
        assert kw in txt, f"安全边界缺关键词:{kw}"
