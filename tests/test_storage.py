import json
import os
import zipfile
from datetime import UTC, datetime, timedelta

from PIL import Image

from cyberbody.config import redact_secrets
from cyberbody.models import Rect, SessionState, TargetWindow
from cyberbody.storage import SessionStore


def target():
    return TargetWindow(
        hwnd=100,
        pid=200,
        title="Test",
        window_rect=Rect(0, 0, 800, 600),
        client_rect=Rect(10, 30, 790, 590),
    )


def test_session_store_writes_summary_events_and_images(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    summary = store.start("do a thing", "gpt-5.6", target())
    source = Image.new("RGB", (80, 60), "white")
    source_path, model_path = store.save_capture(1, source, source)
    store.increment_action()
    store.set_state(SessionState.COMPLETED, final_message="done")

    saved = json.loads((store.session_dir / "session.json").read_text(encoding="utf-8"))
    assert saved["session_id"] == summary.session_id
    assert saved["state"] == "completed"
    assert saved["action_count"] == 1
    assert source_path.exists() and model_path.exists()
    assert (store.session_dir / "events.jsonl").exists()


def test_cleanup_expired_only_removes_old_session_directories(tmp_path):
    root = tmp_path / "sessions"
    old = root / "old"
    fresh = root / "fresh"
    old.mkdir(parents=True)
    fresh.mkdir()
    now = datetime.now(UTC)
    old_time = (now - timedelta(days=10)).timestamp()
    os.utime(old, (old_time, old_time))

    removed = SessionStore.cleanup_expired(7, root=root, now=now)
    assert old.resolve() in removed
    assert not old.exists()
    assert fresh.exists()


def test_redaction_removes_secret_fields_and_openai_keys():
    redacted = redact_secrets(
        {"api_key": "abc", "nested": {"password": "p", "text": "sk-abcdefghijklmnop"}}
    )
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["text"] == "[REDACTED]"


def test_export_contains_only_relative_session_files(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    store.start("inspect", "gpt-5.6", target())
    destination = tmp_path / "export.zip"

    store.export(destination)

    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
    assert {"session.json", "events.jsonl"} <= names
    assert all(not name.startswith("/") and ":" not in name for name in names)


def test_clear_all_removes_only_session_directories(tmp_path):
    root = tmp_path / "sessions"
    (root / "one").mkdir(parents=True)
    (root / "two").mkdir()
    marker = root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    assert SessionStore.clear_all(root) == 2
    assert marker.exists()
