from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APP_NAME = "cyberbody"
KEYRING_SERVICE = "cyberbody/OpenAI"
KEYRING_USER = "default"

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b", re.IGNORECASE),
    re.compile(r"\bOPENAI_API_KEY\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
)


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".cyberbody"


@dataclass(slots=True)
class AppConfig:
    model: str = "gpt-5.6"
    retention_days: int = 7
    max_actions: int = 50
    max_seconds: int = 600
    preview_delay_ms: int = 500
    screenshot_max_width: int = 1600
    screenshot_max_height: int = 900
    api_timeout_seconds: float = 60.0
    api_retries: int = 3

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        config_path = path or app_data_dir() / "config.json"
        if not config_path.exists():
            return cls()
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        allowed = cls.__dataclass_fields__.keys()
        values = {key: value for key, value in raw.items() if key in allowed}
        try:
            config = cls(**values)
            config.validate()
        except (TypeError, ValueError):
            return cls()
        return config

    def validate(self) -> None:
        if not self.model.strip():
            raise ValueError("Model name cannot be empty")
        if not 1 <= self.retention_days <= 3650:
            raise ValueError("retention_days must be between 1 and 3650")
        if not 1 <= self.max_actions <= 1000:
            raise ValueError("max_actions must be between 1 and 1000")
        if not 10 <= self.max_seconds <= 86400:
            raise ValueError("max_seconds must be between 10 and 86400")
        if not 0 <= self.preview_delay_ms <= 10000:
            raise ValueError("preview_delay_ms must be between 0 and 10000")
        if self.screenshot_max_width < 640 or self.screenshot_max_height < 480:
            raise ValueError("Screenshot limits are too small")
        if not 5 <= self.api_timeout_seconds <= 600:
            raise ValueError("api_timeout_seconds must be between 5 and 600")
        if not 0 <= self.api_retries <= 10:
            raise ValueError("api_retries must be between 0 and 10")

    def save(self, path: Path | None = None) -> Path:
        self.validate()
        config_path = path or app_data_dir() / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = config_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(config_path)
        return config_path


class ApiKeyStore:
    @staticmethod
    def get() -> str | None:
        environment_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if environment_key:
            return environment_key
        try:
            import keyring

            value = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception:
            return None
        return value.strip() if value else None

    @staticmethod
    def set(value: str) -> None:
        key = value.strip()
        if not key:
            raise ValueError("API key cannot be empty")
        import keyring

        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)

    @staticmethod
    def delete() -> None:
        try:
            import keyring

            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception:
            return


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(token in lowered for token in ("api_key", "password", "secret", "token")):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_secrets(item)
        return result
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        redacted = value
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    return value
