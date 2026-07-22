from pathlib import Path
from coding_agent_harness.config import load_config


def test_load_config_parses_fields(tmp_path):
    cfg_yaml = tmp_path / "c.yaml"
    cfg_yaml.write_text(
        "project_root: ./ws\n"
        "llm: {provider: openai-compatible, base_url: 'http://x', model: m}\n"
        "guardrails:\n"
        "  max_rounds: 5\n  same_category_prompt_at: 2\n"
        "  same_category_stop_at: 3\n  no_change_stop_at: 2\n"
        "  approval_timeout_sec: 60\n"
        "  shell_blacklist: [rm -rf]\n  shell_whitelist: [pytest]\n"
        "feedback:\n  pytest_args: [-q]\n  max_traceback_excerpt_lines: 4\n"
        "memory:\n  fixes_path: ./f.json\n  conventions_path: ./c.json\n  retrieve_top_k: 2\n"
    )
    cfg = load_config(cfg_yaml)
    assert cfg.project_root == Path("./ws")
    assert cfg.guardrails.max_rounds == 5
    assert "rm -rf" in cfg.guardrails.shell_blacklist
    assert cfg.memory.retrieve_top_k == 2


def test_load_config_applies_defaults_when_missing(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text("project_root: ./ws\nllm: {base_url: 'http://x', model: m}\n")
    cfg = load_config(f)
    assert cfg.guardrails.max_rounds == 8  # 默认
    assert cfg.guardrails.same_category_stop_at == 3
