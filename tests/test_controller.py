import io
import threading

from PIL import Image

from cyberbody.api import ComputerTurn
from cyberbody.controller import AutomationController, ControllerEvents
from cyberbody.models import CaptureFrame, ComputerAction, Rect, SessionState, TargetWindow
from cyberbody.safety import InspectionResult, SafetyGate
from cyberbody.storage import SessionStore


class FakeWindows:
    def activate(self, _target):
        return True

    def validate(self, _target, require_foreground=True):
        return True, ""


class FakeCapture:
    def __init__(self, store):
        self.store = store
        self.counter = 0

    def capture(self, target, round_index):
        self.counter += 1
        image = Image.new("RGB", (200, 100), (self.counter * 30, 20, 30))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        source, model = self.store.save_capture(round_index, image, image)
        frame = CaptureFrame(
            round_index=round_index,
            source_rect=target.client_rect,
            source_width=200,
            source_height=100,
            model_width=200,
            model_height=100,
            source_path=source,
            model_path=model,
            perceptual_hash=self.counter,
            model_png=buffer.getvalue(),
        )
        return frame, image


class FakeExecutor:
    def __init__(self):
        self.actions = []

    def execute(self, action, _target, _frame, _stop):
        self.actions.append(action)

    def release_all(self):
        return None


class FakeApi:
    def __init__(self, risky=False):
        self.continues = 0
        self.risky = risky
        self.acknowledged = 0

    def start(self, _task, _stop):
        return ComputerTurn("resp_1", "call_1", (ComputerAction(type="screenshot"),), "")

    def continue_with_screenshot(self, _previous, _call, _png, _stop):
        self.continues += 1
        if self.continues == 1:
            label = "删除" if self.risky else "打开"
            action = ComputerAction(type="click", x=50, y=40)
            return ComputerTurn("resp_2", "call_2", (action,), label)
        return ComputerTurn("resp_3", None, (), "完成")

    def inspect_action(self, _task, _action, _png, _stop):
        return InspectionResult(
            purpose="点击删除" if self.risky else "打开项目",
            target_label="删除" if self.risky else "项目",
        )

    def acknowledge_safety_checks(self):
        self.acknowledged += 1


def make_target():
    return TargetWindow(
        hwnd=1,
        pid=2,
        title="Test",
        window_rect=Rect(0, 0, 200, 100),
        client_rect=Rect(0, 0, 200, 100),
    )


def test_controller_completes_screenshot_action_loop(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    executor = FakeExecutor()
    finished = threading.Event()
    final = {}
    events = ControllerEvents(
        confirmation=lambda _proposal, _handoff: True,
        finished=lambda state, message: (
            final.update(state=state, message=message),
            finished.set(),
        ),
    )
    api = FakeApi()
    controller = AutomationController(
        FakeWindows(),
        store,
        FakeCapture(store),
        executor,
        SafetyGate(),
        lambda _callback: api,
        events,
        preview_delay_ms=0,
    )
    controller.start("打开项目", make_target(), "vision-model", "action-model")
    assert finished.wait(3)
    assert final["state"] == SessionState.COMPLETED
    assert [action.type for action in executor.actions] == ["click"]
    assert store.summary.action_count == 1
    assert store.summary.round_count == 2


def test_controller_does_not_execute_rejected_risk_action(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    executor = FakeExecutor()
    finished = threading.Event()
    final = {}
    events = ControllerEvents(
        confirmation=lambda _proposal, _handoff: False,
        finished=lambda state, message: (
            final.update(state=state, message=message),
            finished.set(),
        ),
    )
    api = FakeApi(risky=True)
    controller = AutomationController(
        FakeWindows(),
        store,
        FakeCapture(store),
        executor,
        SafetyGate(),
        lambda _callback: api,
        events,
        preview_delay_ms=0,
    )
    controller.start("删除记录", make_target(), "vision-model", "action-model")
    assert finished.wait(3)
    assert final["state"] == SessionState.STOPPED
    assert executor.actions == []
    assert api.acknowledged == 0


def test_controller_acknowledges_only_after_approved_risk_action(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    executor = FakeExecutor()
    finished = threading.Event()
    api = FakeApi(risky=True)
    controller = AutomationController(
        FakeWindows(),
        store,
        FakeCapture(store),
        executor,
        SafetyGate(),
        lambda _callback: api,
        ControllerEvents(
            confirmation=lambda _proposal, _handoff: True,
            finished=lambda _state, _message: finished.set(),
        ),
        preview_delay_ms=0,
    )

    controller.start("删除记录", make_target(), "computer-model", "computer-model", "native")

    assert finished.wait(3)
    assert api.acknowledged == 1
    assert [action.type for action in executor.actions] == ["click"]
