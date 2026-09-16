import os


def test_application_icon_assets_are_available():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from cyberbody.ui import application_icon_path

    _app = QApplication.instance() or QApplication([])
    png_path = application_icon_path()
    ico_path = png_path.with_suffix(".ico")

    assert png_path.is_file()
    assert not QIcon(str(png_path)).isNull()
    assert ico_path.is_file()
    with Image.open(ico_path) as icon:
        assert icon.info["sizes"] == {
            (16, 16),
            (20, 20),
            (24, 24),
            (32, 32),
            (40, 40),
            (48, 48),
            (64, 64),
            (96, 96),
            (128, 128),
            (256, 256),
        }


def test_live_viewport_renders_frame_and_action_marker(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtWidgets import QApplication

    from cyberbody.models import (
        ActionProposal,
        CaptureFrame,
        ComputerAction,
        Rect,
        RiskCategory,
        SafetyDecision,
    )
    from cyberbody.ui import LiveViewport

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "frame.png"
    Image.new("RGB", (320, 180), "#20242c").save(path)
    frame = CaptureFrame(
        round_index=1,
        source_rect=Rect(0, 0, 320, 180),
        source_width=320,
        source_height=180,
        model_width=320,
        model_height=180,
        model_path=path,
    )
    proposal = ActionProposal(
        action=ComputerAction(type="click", x=160, y=90),
        purpose="打开项目",
        target_label="打开按钮",
        risk_category=RiskCategory.NONE,
        decision=SafetyDecision.ALLOW,
    )
    viewport = LiveViewport()
    viewport.resize(640, 400)
    viewport.set_frame(frame)
    viewport.set_proposal(proposal)
    viewport.show()
    app.processEvents()

    rendered = viewport.grab().toImage()

    assert not rendered.isNull()
    assert rendered.width() == 640
    assert rendered.height() == 400
    viewport.close()


def test_workspace_window_builds_native_and_dual_modes(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from cyberbody import ui
    from cyberbody.config import AppConfig

    class FakeCommandServer:
        def __init__(self, _handler):
            pass

        @staticmethod
        def listen():
            return True

        @staticmethod
        def close():
            return None

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(ui.AppConfig, "load", staticmethod(lambda _path=None: AppConfig()))
    monkeypatch.setattr(ui.ApiKeyStore, "get", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(ui, "LocalCommandServer", FakeCommandServer)
    monkeypatch.setattr(ui.WindowManager, "enumerate_windows", lambda *_args, **_kwargs: [])
    app = QApplication.instance() or QApplication([])

    window = ui.CyberbodyWindow()

    assert window.mode_combo.currentData() == "native"
    assert window.settings_stack.currentIndex() == 0
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("dual"))
    app.processEvents()
    assert window.settings_stack.currentIndex() == 1
    assert window.engine_badge.text() == "DUAL MODEL"
    window.close()
