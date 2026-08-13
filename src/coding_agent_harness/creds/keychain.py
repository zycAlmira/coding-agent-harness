"""凭据安全存储。macOS Keychain / Windows Credential Manager / Linux Secret Service。绝不回显明文。

§3.1 红线:LLM/付费 API key 绝不硬编码、绝不进 git(含历史)、不进日志/shell history/
明文配置。本模块用 keyring 后端落到操作系统凭据库;status() 只返回布尔存在性,
绝不回显明文。首次运行由 CLI 引导隐藏录入。

容器兼容:Linux 容器(Docker 部署)可能无 keyring 后端(无 Keychain/Secret Service),
所有方法容错为"未配置"而非抛异常——mock 模式本就不需要 key,WebUI 不应因
凭据模块崩溃。
"""
from __future__ import annotations
import keyring

SERVICE = "coding-agent-harness"


def _keyring_available() -> bool:
    """keyring 是否有可用后端(容器内无 Keychain/Secret Service 时返回 False)。

    注意:keyring.get_keyring() 在无后端时返回 fail 后端(不抛异常),
    真正抛 NoKeyringError 的是 get_password/set_password 等操作——
    故须用 try/except 包实际调用。
    """
    try:
        keyring.get_password(SERVICE, "__probe__")
        return True
    except Exception:
        return False


class Creds:
    def __init__(self, service: str = SERVICE):
        self.service = service

    def set(self, api_key: str, base_url: str, model: str) -> None:
        if not _keyring_available():
            return  # 无后端:静默跳过(容器 mock 模式无需存储)
        keyring.set_password(self.service, "api_key", api_key)
        keyring.set_password(self.service, "base_url", base_url)
        keyring.set_password(self.service, "model", model)

    def get(self) -> tuple[str, str, str] | None:
        if not _keyring_available():
            return None
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
        if not _keyring_available():
            return {"set": False}
        return {"set": bool(keyring.get_password(self.service, "api_key"))}

    def info(self) -> dict:
        """返回非敏感配置(base_url、model),不回显 api_key。供前端展示。"""
        if not _keyring_available():
            return {"configured": False, "base_url": "", "model": ""}
        if not keyring.get_password(self.service, "api_key"):
            return {"configured": False, "base_url": "", "model": ""}
        return {
            "configured": True,
            "base_url": keyring.get_password(self.service, "base_url") or "",
            "model": keyring.get_password(self.service, "model") or "",
        }

    def set_model(self, model: str, base_url: str | None = None) -> None:
        """更新模型名(和可选的 base_url),保留现有 api_key。"""
        cred = self.get()
        if cred:
            self.set(cred[0], base_url or cred[1], model)

    def clear(self) -> None:
        if not _keyring_available():
            return
        for u in ("api_key", "base_url", "model"):
            try:
                keyring.delete_password(self.service, u)
            except keyring.errors.PasswordDeleteError:
                pass
