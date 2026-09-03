from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .config import app_data_dir, redact_secrets
from .models import ActionProposal, SessionState, SessionSummary, TargetWindow


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SessionStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_data_dir() / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)
        self.summary: SessionSummary | None = None
        self.session_dir: Path | None = None

    def start(
        self,
        task: str,
        vision_model: str,
        action_model: str,
        target: TargetWindow,
    ) -> SessionSummary:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"
        self.session_dir = self.root / session_id
        self.session_dir.mkdir(parents=True, exist_ok=False)
        self.summary = SessionSummary(
            session_id=session_id,
            task=task,
            vision_model=vision_model,
            action_model=action_model,
            target=target.public_dict(),
            state=SessionState.PLANNING,
            started_at=utc_now_iso(),
        )
        self._write_summary()
        self.append_event(
            "session_started",
            {
                "task": task,
                "vision_model": vision_model,
                "action_model": action_model,
            },
        )
        return self.summary

    def set_state(
        self,
        state: SessionState,
        *,
        final_message: str | None = None,
        error: str | None = None,
    ) -> None:
        if self.summary is None:
            return
        self.summary.state = state
        if final_message is not None:
            self.summary.final_message = final_message
        if error is not None:
            self.summary.error = error
        if state in {
            SessionState.COMPLETED,
            SessionState.FAILED,
            SessionState.STOPPED,
            SessionState.TIMED_OUT,
        }:
            self.summary.ended_at = utc_now_iso()
        self._write_summary()
        self.append_event("state_changed", {"state": state.value})

    def increment_action(self) -> None:
        if self.summary:
            self.summary.action_count += 1
            self._write_summary()

    def increment_round(self) -> int:
        if self.summary is None:
            raise RuntimeError("Session has not started")
        self.summary.round_count += 1
        self._write_summary()
        return self.summary.round_count

    def append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.session_dir is None:
            return
        record = {
            "timestamp": utc_now_iso(),
            "type": event_type,
            "payload": redact_secrets(payload),
        }
        with (self.session_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def save_capture(
        self, round_index: int, source_image: Image.Image, model_image: Image.Image
    ) -> tuple[Path, Path]:
        if self.session_dir is None:
            raise RuntimeError("Session has not started")
        source_path = self.session_dir / f"round-{round_index:04d}.png"
        model_path = self.session_dir / f"round-{round_index:04d}-model.png"
        source_image.save(source_path, format="PNG", optimize=True)
        if model_image.size == source_image.size:
            shutil.copy2(source_path, model_path)
        else:
            model_image.save(model_path, format="PNG", optimize=True)
        self.append_event(
            "capture_saved",
            {
                "round": round_index,
                "source": source_path.name,
                "model": model_path.name,
                "source_size": source_image.size,
                "model_size": model_image.size,
            },
        )
        return source_path, model_path

    def save_annotated(
        self,
        round_index: int,
        model_image: Image.Image,
        proposal: ActionProposal,
    ) -> Path:
        if self.session_dir is None:
            raise RuntimeError("Session has not started")
        image = model_image.convert("RGBA")
        draw = ImageDraw.Draw(image)
        points = proposal.action.model_points()
        if proposal.action.type == "drag" and len(points) >= 2:
            draw.line(points, fill=(255, 166, 0, 255), width=5)
        for x, y in points:
            radius = 16
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                outline=(255, 80, 80, 255),
                width=5,
            )
        label = proposal.target_label or proposal.action.type
        draw.rectangle((8, 8, min(image.width - 8, 600), 44), fill=(16, 24, 40, 220))
        draw.text((16, 16), label, fill=(255, 255, 255, 255))
        path = self.session_dir / f"round-{round_index:04d}-annotated.png"
        image.convert("RGB").save(path, format="PNG", optimize=True)
        return path

    def export(self, destination: Path) -> Path:
        if self.session_dir is None:
            raise RuntimeError("Session has not started")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in self.session_dir.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(self.session_dir))
        return destination

    def _write_summary(self) -> None:
        if self.session_dir is None or self.summary is None:
            return
        path = self.session_dir / "session.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.summary.public_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    @classmethod
    def cleanup_expired(
        cls, retention_days: int, root: Path | None = None, now: datetime | None = None
    ) -> list[Path]:
        sessions_root = (root or app_data_dir() / "sessions").resolve()
        if not sessions_root.exists():
            return []
        cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        removed: list[Path] = []
        for child in sessions_root.iterdir():
            resolved = child.resolve()
            if resolved.parent != sessions_root or not resolved.is_dir():
                continue
            modified = datetime.fromtimestamp(resolved.stat().st_mtime, tz=UTC)
            if modified < cutoff:
                shutil.rmtree(resolved)
                removed.append(resolved)
        return removed

    @classmethod
    def clear_all(cls, root: Path | None = None) -> int:
        sessions_root = (root or app_data_dir() / "sessions").resolve()
        if not sessions_root.exists():
            return 0
        count = 0
        for child in sessions_root.iterdir():
            resolved = child.resolve()
            if resolved.parent == sessions_root and resolved.is_dir():
                shutil.rmtree(resolved)
                count += 1
        return count
