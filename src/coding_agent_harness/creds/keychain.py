"""凭据安全存储。macOS Keychain / Windows Credential Manager / Linux Secret Service。绝不回显明文。

§3.1 红线:LLM/付费 API key 绝不硬编码、绝不进 git(含历史)、不进日志/shell history/
明文配置。本模块用 keyring 后端落到操作系统凭据库;status() 只返回布尔存在性,
绝不回显明文。首次运行由 CLI 引导隐藏录入。

容器兼容:Linux 容器(Docker 部署)可能无 keyring 后端(无 Keychain/Secret Service),
自动回落到「文件后端」——权限 600 的 JSON 文件(路径由 HARNESS_CREDS_FILE 指定,
默认 /app/data/creds.json),供 real 模式在容器内正常录入/使用凭据。
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import keyring

SERVICE = "coding-agent-harness"
DEFAULT_FILE = "/app/data/creds.json"


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


def _file_path() -> Path:
    return Path(os.environ.get("HARNESS_CREDS_FILE", DEFAULT_FILE))


def _file_read() -> dict:
    p = _file_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _file_write(data: dict) -> None:
    p = _file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(p, 0o600)  # 仅属主可读写,防同机其他用户


class Creds:
    def __init__(self, service: str = SERVICE):
        self.service = service

    def _store(self) -> bool:
        """返回 True 用 keyring,False 用文件后端。"""
        return _keyring_available()

    def set(self, api_key: str, base_url: str, model: str) -> None:
        if self._store():
            keyring.set_password(self.service, "api_key", api_key)
            keyring.set_password(self.service, "base_url", base_url)
            keyring.set_password(self.service, "model", model)
        else:
            data = _file_read()
            data.update({"api_key": api_key, "base_url": base_url, "model": model})
            _file_write(data)

    def get(self) -> tuple[str, str, str] | None:
        if self._store():
            k = keyring.get_password(self.service, "api_key")
            if not k:
                return None
            return (
                k,
                keyring.get_password(self.service, "base_url") or "",
                keyring.get_password(self.service, "model") or "",
            )
        data = _file_read()
        if not data.get("api_key"):
            return None
        return (data["api_key"], data.get("base_url", ""), data.get("model", ""))

    def status(self) -> dict:
        # 只返回布尔存在性,绝不回显明文 key。
        if self._store():
            return {"set": bool(keyring.get_password(self.service, "api_key"))}
        return {"set": bool(_file_read().get("api_key"))}

    def info(self) -> dict:
        """返回非敏感配置(base_url、model),不回显 api_key。供前端展示。"""
        if self._store():
            if not keyring.get_password(self.service, "api_key"):
                return {"configured": False, "base_url": "", "model": ""}
            return {
                "configured": True,
                "base_url": keyring.get_password(self.service, "base_url") or "",
                "model": keyring.get_password(self.service, "model") or "",
            }
        data = _file_read()
        if not data.get("api_key"):
            return {"configured": False, "base_url": "", "model": ""}
        return {"configured": True, "base_url": data.get("base_url", ""), "model": data.get("model", "")}

    def set_model(self, model: str, base_url: str | None = None) -> None:
        """更新模型名(和可选的 base_url),保留现有 api_key。"""
        cred = self.get()
        if cred:
            self.set(cred[0], base_url or cred[1], model)

    def clear(self) -> None:
        if self._store():
            for u in ("api_key", "base_url", "model"):
                try:
                    keyring.delete_password(self.service, u)
                except keyring.errors.PasswordDeleteError:
                    pass
        else:
            try:
                _file_path().unlink()
            except OSError:
                pass
