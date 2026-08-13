"""Dockerfile 的确定性单测(§A.4 精神:分发产物也要可验证)。

解析 Dockerfile 断言关键指令:FROM python 基镜像、EXPOSE 8000、CMD 含 harness serve、
无硬编码 key(§3.1)、用 uv 锁依赖;.dockerignore 排除 .venv/密钥。
本地另有 docker build+run 集成验证(见 task-23-report)。
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DF = _ROOT / "Dockerfile"


def _lines() -> list[str]:
    assert _DF.exists(), f"缺 {_DF}"
    return _DF.read_text().splitlines()


def test_from_python_base():
    assert any(line.startswith("FROM") and "python" in line for line in _lines()), "应 FROM python 基镜像"


def test_exposes_8000():
    assert any(line.startswith("EXPOSE 8000") for line in _lines()), "应 EXPOSE 8000(serve 默认端口)"


def test_cmd_runs_harness_serve():
    txt = "\n".join(_lines())
    assert "harness" in txt and "serve" in txt, "CMD 应启动 harness serve"


def test_no_hardcoded_key():
    # §3.1:容器绝不预置 key
    txt = "\n".join(_lines())
    for needle in ["sk-", "api_key=", "api_key:", "DEEPSEEK", "OPENAI_API_KEY"]:
        assert needle.lower() not in txt.lower(), f"Dockerfile 含疑似硬编码 key:{needle}"


def test_uses_uv_and_lock():
    # 用 uv + uv.lock 保可复现
    txt = "\n".join(_lines())
    assert "uv" in txt, "应用 uv 安装依赖"
    assert "uv.lock" in txt or "uv sync" in txt, "应基于 uv.lock/sync 锁依赖"


def test_dockerignore_excludes_venv_and_secrets():
    di = _ROOT / ".dockerignore"
    assert di.exists(), "缺 .dockerignore"
    txt = di.read_text()
    for needle in [".venv", "__pycache__", ".env", ".git"]:
        assert needle in txt, f".dockerignore 应排除 {needle}"


def test_has_healthcheck():
    # HEALTHCHECK 探本地 8000(与 fly.toml checks 对齐)
    txt = "\n".join(_lines())
    assert "HEALTHCHECK" in txt, "应有 HEALTHCHECK"
    assert "127.0.0.1:8000" in txt, "HEALTHCHECK 应探本地 8000"


def test_no_dev_extras():
    # 生产镜像不含 pytest/ruff(--no-dev)
    txt = "\n".join(_lines())
    assert "--no-dev" in txt, "生产镜像应 --no-dev(不含 dev extras)"

