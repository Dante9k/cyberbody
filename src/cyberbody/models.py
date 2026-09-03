from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class SessionState(StrEnum):
    IDLE = "idle"
    PLANNING = "planning"
    PREVIEWING = "previewing"
    EXECUTING = "executing"
    OBSERVING = "observing"
    PAUSED = "paused"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    TIMED_OUT = "timed_out"


TERMINAL_STATES = {
    SessionState.COMPLETED,
    SessionState.FAILED,
    SessionState.STOPPED,
    SessionState.TIMED_OUT,
}


class RiskCategory(StrEnum):
    NONE = "none"
    EXTERNAL_COMMUNICATION = "external_communication"
    DESTRUCTIVE = "destructive"
    FINANCIAL = "financial"
    SENSITIVE_DATA = "sensitive_data"
    ACCOUNT_PERMISSION = "account_permission"
    INSTALL_OR_EXECUTE = "install_or_execute"
    SYSTEM_SETTING = "system_setting"
    CAPTCHA = "captcha"
    SAFETY_BYPASS = "safety_bypass"
    PROMPT_INJECTION = "prompt_injection"
    UNKNOWN = "unknown"


class SafetyDecision(StrEnum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    HANDOFF = "handoff"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def as_bbox(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


@dataclass(slots=True)
class TargetWindow:
    hwnd: int
    pid: int
    title: str
    window_rect: Rect
    client_rect: Rect
    dpi: int = 96
    allowed_owned_hwnds: set[int] = field(default_factory=set)

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["allowed_owned_hwnds"] = sorted(self.allowed_owned_hwnds)
        return result


@dataclass(slots=True)
class CaptureFrame:
    round_index: int
    source_rect: Rect
    source_width: int
    source_height: int
    model_width: int
    model_height: int
    capture_hwnd: int = 0
    source_path: Path | None = None
    model_path: Path | None = None
    perceptual_hash: int = 0
    model_png: bytes = field(default=b"", repr=False)

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        if self.model_width <= 0 or self.model_height <= 0:
            raise ValueError("Invalid model image dimensions")
        source_x = round(float(x) * self.source_width / self.model_width)
        source_y = round(float(y) * self.source_height / self.model_height)
        return self.source_rect.left + source_x, self.source_rect.top + source_y

    def model_point_in_bounds(self, x: float, y: float) -> bool:
        return 0 <= x < self.model_width and 0 <= y < self.model_height


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _normalize_path(path: Iterable[Any] | None) -> tuple[tuple[float, float], ...]:
    result: list[tuple[float, float]] = []
    for point in path or ():
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            result.append((float(point[0]), float(point[1])))
        else:
            x = _value(point, "x")
            y = _value(point, "y")
            if x is None or y is None:
                raise ValueError("Drag path entries must contain x and y")
            result.append((float(x), float(y)))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ComputerAction:
    type: str
    x: float | None = None
    y: float | None = None
    button: str = "left"
    text: str = ""
    keys: tuple[str, ...] = ()
    scroll_x: float = 0
    scroll_y: float = 0
    path: tuple[tuple[float, float], ...] = ()

    @classmethod
    def from_api(cls, action: Any) -> ComputerAction:
        action_type = str(_value(action, "type", "")).strip().casefold()
        if not action_type:
            raise ValueError("Computer action is missing its type")
        raw_x = _value(action, "x")
        raw_y = _value(action, "y")
        return cls(
            type=action_type,
            x=float(raw_x) if raw_x is not None else None,
            y=float(raw_y) if raw_y is not None else None,
            button=str(_value(action, "button", "left") or "left").casefold(),
            text=str(_value(action, "text", "") or ""),
            keys=tuple(str(key) for key in (_value(action, "keys", ()) or ())),
            scroll_x=float(_value(action, "scroll_x", 0) or 0),
            scroll_y=float(_value(action, "scroll_y", 0) or 0),
            path=_normalize_path(_value(action, "path", ())),
        )

    @property
    def is_pointer_action(self) -> bool:
        return self.type in {"click", "double_click", "move", "scroll", "drag"}

    def model_points(self) -> tuple[tuple[float, float], ...]:
        if self.type == "drag":
            return self.path
        if self.x is not None and self.y is not None:
            return ((float(self.x), float(self.y)),)
        return ()

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ActionProposal:
    action: ComputerAction
    purpose: str
    target_label: str
    risk_category: RiskCategory
    decision: SafetyDecision
    reason: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.public_dict(),
            "purpose": self.purpose,
            "target_label": self.target_label,
            "risk_category": self.risk_category.value,
            "decision": self.decision.value,
            "reason": self.reason,
        }


@dataclass(slots=True)
class SessionSummary:
    session_id: str
    task: str
    vision_model: str
    action_model: str
    target: dict[str, Any]
    state: SessionState
    started_at: str
    ended_at: str | None = None
    action_count: int = 0
    round_count: int = 0
    final_message: str = ""
    error: str = ""

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["state"] = self.state.value
        return result


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()
