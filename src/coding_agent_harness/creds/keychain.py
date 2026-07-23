"""凭据安全存储。macOS Keychain / Windows Credential Manager / Linux Secret Service。绝不回显明文。

§3.1 红线:LLM/付费 API key 绝不硬编码、绝不进 git(含历史)、不进日志/shell history/
明文配置。本模块用 keyring 后端落到操作系统凭据库;status() 只返回布尔存在性,
绝不回显明文。首次运行由 CLI 引导隐藏录入。
"""
from __future__ import annotations
import keyring

SERVICE = "coding-agent-harness"


class Creds:
    def __init__(self, service: str = SERVICE):
        self.service = service

    def set(self, api_key: str, base_url: str, model: str) -> None:
        keyring.set_password(self.service, "api_key", api_key)
        keyring.set_password(self.service, "base_url", base_url)
        keyring.set_password(self.service, "model", model)

    def get(self) -> tuple[str, str, str] | None:
        k = keyring.get_password(self.service, "api_key")
        if not k:
            return None
        return (
            k,
            keyring.get_password(self.service, "base_url") or "",
            keyring.get_password(self.service, "model") or "",
        )

    def status(self) -> dict:
        # 只返回布尔存在性,绝不回显明文 key。
        return {"set": bool(keyring.get_password(self.service, "api_key"))}

    def clear(self) -> None:
        for u in ("api_key", "base_url", "model"):
            try:
                keyring.delete_password(self.service, u)
            except keyring.errors.PasswordDeleteError:
                pass
