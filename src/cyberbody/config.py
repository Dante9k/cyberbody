from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

APP_NAME = "cyberbody"
LEGACY_KEYRING_SERVICE = "cyberbody/OpenAI"
KEYRING_SERVICE_PREFIXES = {
    "computer": "cyberbody/ComputerAPI",
    "vision": "cyberbody/VisionAPI",
    "action": "cyberbody/ActionAPI",
}
KEYRING_USER = "default"

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:OPENAI_API_KEY|CYBERBODY_(?:COMPUTER|VISION|ACTION)_API_KEY)\s*[:=]\s*[^\s,;]+",
        re.IGNORECASE,
    ),
)


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".cyberbody"


@dataclass(slots=True)
class AppConfig:
    execution_mode: str = "native"
    computer_model: str = "gpt-5.6-sol"
    computer_base_url: str = ""
    vision_model: str = "gpt-5.6"
    action_model: str = "gpt-5.6"
    vision_base_url: str = ""
    action_base_url: str = ""
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
        # Configurations written before native mode existed keep their established behavior.
        if "execution_mode" not in raw:
            raw["execution_mode"] = "dual"
        legacy_model = raw.get("model")
        if isinstance(legacy_model, str) and legacy_model.strip():
            raw.setdefault("vision_model", legacy_model)
            raw.setdefault("action_model", legacy_model)
        allowed = cls.__dataclass_fields__.keys()
        values = {key: value for key, value in raw.items() if key in allowed}
        try:
            config = cls(**values)
            config.validate()
        except (TypeError, ValueError):
            return cls()
        return config

    def validate(self) -> None:
        if self.execution_mode not in {"native", "dual"}:
            raise ValueError("execution_mode must be native or dual")
        if not self.computer_model.strip():
            raise ValueError("Computer model name cannot be empty")
        if not self.vision_model.strip():
            raise ValueError("Vision model name cannot be empty")
        if not self.action_model.strip():
            raise ValueError("Action model name cannot be empty")
        _validate_base_url("computer_base_url", self.computer_base_url)
        _validate_base_url("vision_base_url", self.vision_base_url)
        _validate_base_url("action_base_url", self.action_base_url)
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
    def get(
        role: str,
        base_url: str = "",
        *,
        include_openai_fallback: bool = False,
    ) -> str | None:
        service = _keyring_service(role, base_url)
        environment_key = os.environ.get(f"CYBERBODY_{role.upper()}_API_KEY", "").strip()
        if environment_key:
            return environment_key
        if include_openai_fallback:
            openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
            if openai_key:
                return openai_key
        try:
            import keyring

            value = keyring.get_password(service, KEYRING_USER)
            if not value and include_openai_fallback:
                value = keyring.get_password(LEGACY_KEYRING_SERVICE, KEYRING_USER)
        except Exception:
            return None
        return value.strip() if value else None

    @staticmethod
    def set(role: str, value: str, base_url: str = "") -> None:
        service = _keyring_service(role, base_url)
        key = value.strip()
        if not key:
            raise ValueError("API key cannot be empty")
        import keyring

        keyring.set_password(service, KEYRING_USER, key)

    @staticmethod
    def delete(role: str, base_url: str = "") -> None:
        service = _keyring_service(role, base_url)
        try:
            import keyring

            keyring.delete_password(service, KEYRING_USER)
        except Exception:
            return


def _keyring_service(role: str, base_url: str) -> str:
    try:
        prefix = KEYRING_SERVICE_PREFIXES[role]
    except KeyError:
        raise ValueError(f"Unknown API role: {role}") from None
    endpoint = base_url.strip().rstrip("/") or "https://api.openai.com/v1"
    endpoint_id = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}/{endpoint_id}"


def is_openai_base_url(value: str) -> bool:
    normalized = value.strip().rstrip("/").casefold()
    return not normalized or normalized in {
        "https://api.openai.com",
        "https://api.openai.com/v1",
    }


def _validate_base_url(name: str, value: str) -> None:
    normalized = value.strip()
    if not normalized:
        return
    parsed = urlsplit(normalized)
    if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{name} must be a URL without embedded credentials")
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and (parsed.hostname or "").casefold() in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        return
    raise ValueError(f"{name} must use HTTPS, except for a local loopback endpoint")


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
