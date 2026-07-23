"""CI 配置的确定性单测(§A.4 精神:配置也要可验证)。

解析 `.gitlab-ci.yml`,断言含名为 unit-test 的 job(通用 §五.6 硬要求)
且其 script 跑 pytest、属 test stage;并验证容器分发 build-image job 存在(§4.10)。
本地无法跑真实 GitLab pipeline,以此单测替代性地、确定性地保护配置正确性。
"""
import yaml
from pathlib import Path

_CI = Path(__file__).resolve().parents[2] / ".gitlab-ci.yml"


def _load() -> dict:
    assert _CI.exists(), f"缺 {_CI}"
    data = yaml.safe_load(_CI.read_text())
    assert isinstance(data, dict), ".gitlab-ci.yml 顶层不是 dict"
    return data


def _script_lines(job: dict) -> list[str]:
    s = job.get("script") or []
    return [s] if isinstance(s, str) else list(s)


def test_ci_file_exists_and_parses():
    _load()


def test_has_unit_test_job_with_pytest():
    data = _load()
    assert "unit-test" in data, "缺名为 unit-test 的 job(通用 §五.6 硬要求)"
    joined = "\n".join(_script_lines(data["unit-test"]))
    assert "pytest" in joined, "unit-test job 的 script 必须含 pytest"


def test_unit_test_in_test_stage():
    data = _load()
    assert "test" in (data.get("stages") or []), "stages 应含 test"
    assert data["unit-test"].get("stage") == "test"


def test_build_image_job_present():
    # 容器分发(§4.10):CI 须含镜像构建步骤
    data = _load()
    assert "build-image" in data, "容器分发要求 CI 含 build-image job(§4.10)"
    joined = "\n".join(_script_lines(data["build-image"]))
    assert "docker build" in joined


def test_unit_test_runs_on_push():
    # §4.8:每次 push/MR 自动跑测试
    data = _load()
    rules = data["unit-test"].get("rules") or []
    assert rules, "unit-test 须有 rules 以在 push/MR 触发"
    conds = "\n".join(str(r) for r in rules)
    assert "merge_request_event" in conds or "CI_COMMIT_BRANCH" in conds, (
        "unit-test 的 rules 应覆盖 MR 与分支 push"
    )


def test_cache_key_locks_uv_lock():
    # cache key 锁 uv.lock:改依赖时缓存自动失效
    data = _load()
    cache = data.get("cache") or {}
    key = cache.get("key") or {}
    files = key.get("files") if isinstance(key, dict) else None
    assert files and "uv.lock" in files, "cache.key.files 应含 uv.lock"

