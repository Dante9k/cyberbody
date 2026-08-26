from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .api import ApiStopped, OpenAIComputerClient
from .capture import CaptureService, load_frame_image
from .input import ActionExecutionError, InputExecutor
from .models import (
    ActionProposal,
    CaptureFrame,
    ComputerAction,
    RiskCategory,
    SafetyDecision,
    SessionState,
    TargetWindow,
    hamming_distance,
)
from .safety import InspectionResult, SafetyGate
from .storage import SessionStore
from .windows import WindowManager


@dataclass(slots=True)
class ControllerEvents:
    state: Callable[[SessionState, str], None] = lambda _state, _message: None
    log: Callable[[str, str], None] = lambda _level, _message: None
    frame: Callable[[CaptureFrame], None] = lambda _frame: None
    proposal: Callable[[ActionProposal, CaptureFrame], None] = lambda _proposal, _frame: None
    confirmation: Callable[[ActionProposal, bool], bool] = lambda _proposal, _handoff: False
    finished: Callable[[SessionState, str], None] = lambda _state, _message: None
    api_status: Callable[[str], None] = lambda _message: None


class AutomationController:
    def __init__(
        self,
        windows: WindowManager,
        store: SessionStore,
        capture: CaptureService,
        executor: InputExecutor,
        safety: SafetyGate,
        api_factory: Callable[[Callable[[str], None]], OpenAIComputerClient],
        events: ControllerEvents | None = None,
        *,
        max_actions: int = 50,
        max_seconds: int = 600,
        preview_delay_ms: int = 500,
    ) -> None:
        self.windows = windows
        self.store = store
        self.capture = capture
        self.executor = executor
        self.safety = safety
        self.api_factory = api_factory
        self.events = events or ControllerEvents()
        self.max_actions = max_actions
        self.max_seconds = max_seconds
        self.preview_delay_ms = preview_delay_ms
        self.state = SessionState.IDLE
        self.target: TargetWindow | None = None
        self.task = ""
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._run_gate = threading.Event()
        self._run_gate.set()
        self._state_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, task: str, target: TargetWindow, model: str) -> None:
        if self.is_running:
            raise RuntimeError("已有任务正在运行")
        normalized = task.strip()
        if not normalized:
            raise ValueError("任务描述不能为空")
        valid, reason = self.windows.validate(target, require_foreground=False)
        if not valid:
            raise ValueError(reason)
        self.task = normalized
        self.target = target
        self._stop.clear()
        self._run_gate.set()
        self.store.start(normalized, model, target)
        self._thread = threading.Thread(
            target=self._run,
            name="cyberbody-automation",
            args=(model,),
            daemon=True,
        )
        self._thread.start()

    def pause(self, message: str = "已由用户暂停") -> None:
        if not self.is_running:
            return
        self._run_gate.clear()
        self._set_state(SessionState.PAUSED, message)

    def resume(self) -> None:
        if not self.is_running or self._stop.is_set():
            return
        if self.target is not None:
            self.windows.activate(self.target)
        self._run_gate.set()
        self._set_state(SessionState.OBSERVING, "正在继续任务")

    def stop(self, message: str = "已由用户停止") -> None:
        self._stop.set()
        self._run_gate.set()
        threading.Thread(target=self.executor.release_all, daemon=True).start()
        if self.is_running:
            self.events.log("warning", message)
        else:
            self._set_state(SessionState.STOPPED, message)

    def status(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "running": self.is_running,
            "task": self.task,
            "target": self.target.title if self.target else "",
            "session_id": self.store.summary.session_id if self.store.summary else "",
        }

    def _run(self, model: str) -> None:
        started = time.monotonic()
        current_frame: CaptureFrame | None = None
        last_hash: int | None = None
        stagnant_rounds = 0
        try:
            assert self.target is not None
            self.windows.activate(self.target)
            time.sleep(0.2)
            self._check_window(require_foreground=True)
            api = self.api_factory(self.events.api_status)
            self._set_state(SessionState.PLANNING, "正在理解任务")
            turn = api.start(self.task, self._stop)

            while True:
                self._wait_until_runnable()
                self._check_limits(started)
                if not turn.has_computer_call:
                    message = turn.final_text or "任务已完成"
                    self.store.append_event("model_completed", {"message": message})
                    self._finish(SessionState.COMPLETED, message)
                    return

                if current_frame is None:
                    current_frame = self._capture_round()
                    last_hash = current_frame.perceptual_hash
                    turn = api.continue_with_screenshot(
                        turn.response_id,
                        str(turn.call_id),
                        current_frame.model_png,
                        self._stop,
                    )
                    continue

                meaningful_action = False
                handoff_occurred = False
                reobserve_requested = False
                for action in turn.actions:
                    self._wait_until_runnable()
                    self._check_limits(started)
                    if action.type == "screenshot":
                        continue
                    meaningful_action = meaningful_action or action.type not in {"wait", "move"}
                    proposal = self._inspect_and_classify(api, action, current_frame)
                    self.store.append_event("action_proposed", proposal.public_dict())
                    self.store.save_annotated(
                        current_frame.round_index,
                        load_frame_image(current_frame),
                        proposal,
                    )
                    self._set_state(SessionState.PREVIEWING, proposal.purpose)
                    self.events.proposal(proposal, current_frame)

                    if proposal.decision == SafetyDecision.DENY:
                        raise RuntimeError(proposal.reason or "安全策略拒绝了动作")
                    if proposal.decision in {SafetyDecision.CONFIRM, SafetyDecision.HANDOFF}:
                        handoff = proposal.decision == SafetyDecision.HANDOFF
                        self._set_state(
                            SessionState.AWAITING_CONFIRMATION,
                            "需要用户接管" if handoff else "等待风险操作确认",
                        )
                        approved = self.events.confirmation(proposal, handoff)
                        if not approved:
                            self._finish(SessionState.STOPPED, "用户拒绝了风险操作")
                            return
                        self.windows.activate(self.target)
                        time.sleep(0.15)
                        if handoff:
                            self.store.append_event("handoff_completed", proposal.public_dict())
                            handoff_occurred = True
                            break

                    if self._stop.wait(self.preview_delay_ms / 1000):
                        raise ApiStopped("任务已停止")
                    self._check_window(require_foreground=True)
                    self._set_state(SessionState.EXECUTING, proposal.purpose)
                    try:
                        self.executor.execute(action, self.target, current_frame, self._stop)
                    except ActionExecutionError as exc:
                        if "移动或缩放" not in str(exc):
                            raise
                        self.events.log(
                            "warning", "窗口位置已变化，旧坐标未执行；等待继续后重新观察"
                        )
                        self._run_gate.clear()
                        self._set_state(SessionState.PAUSED, str(exc))
                        self._wait_until_runnable()
                        self.windows.activate(self.target)
                        time.sleep(0.15)
                        reobserve_requested = True
                        break
                    self.store.increment_action()
                    self.store.append_event("action_executed", proposal.public_dict())
                    self.events.log("info", f"已执行：{proposal.purpose}")

                self._set_state(SessionState.OBSERVING, "正在观察操作结果")
                new_frame = self._capture_round()
                if meaningful_action and last_hash is not None:
                    if hamming_distance(last_hash, new_frame.perceptual_hash) <= 3:
                        stagnant_rounds += 1
                    else:
                        stagnant_rounds = 0
                last_hash = new_frame.perceptual_hash
                current_frame = new_frame

                if stagnant_rounds >= 3:
                    proposal = ActionProposal(
                        action=ComputerAction(type="screenshot"),
                        purpose="连续三轮画面没有明显变化",
                        target_label="目标窗口",
                        risk_category=RiskCategory.UNKNOWN,
                        decision=SafetyDecision.CONFIRM,
                        reason="继续可能重复无效操作。",
                    )
                    self._set_state(SessionState.AWAITING_CONFIRMATION, "任务可能卡住")
                    if not self.events.confirmation(proposal, False):
                        self._finish(SessionState.STOPPED, "任务因画面无变化而停止")
                        return
                    stagnant_rounds = 0

                turn = api.continue_with_screenshot(
                    turn.response_id,
                    str(turn.call_id),
                    current_frame.model_png,
                    self._stop,
                )
                if handoff_occurred:
                    self.events.log("info", "已在用户接管后重新观察窗口")
                if reobserve_requested:
                    self.events.log("info", "已放弃旧坐标并发送最新窗口截图")
        except ApiStopped:
            self._finish(SessionState.STOPPED, "任务已停止")
        except TimeoutError as exc:
            self.store.append_event("error", {"message": str(exc)})
            self._finish(SessionState.TIMED_OUT, str(exc))
        except Exception as exc:
            self.store.append_event("error", {"message": str(exc), "type": type(exc).__name__})
            if self._stop.is_set():
                self._finish(SessionState.STOPPED, "任务已停止")
            else:
                self._finish(SessionState.FAILED, str(exc))
        finally:
            self.executor.release_all()

    def _capture_round(self) -> CaptureFrame:
        assert self.target is not None
        self._check_window(require_foreground=True)
        round_index = self.store.increment_round()
        frame, _image = self.capture.capture(self.target, round_index)
        self.events.frame(frame)
        self.store.append_event(
            "frame_observed",
            {
                "round": round_index,
                "source_rect": frame.source_rect.as_bbox(),
                "model_size": [frame.model_width, frame.model_height],
                "perceptual_hash": f"{frame.perceptual_hash:064x}",
            },
        )
        return frame

    def _inspect_and_classify(
        self,
        api: OpenAIComputerClient,
        action: ComputerAction,
        frame: CaptureFrame,
    ) -> ActionProposal:
        try:
            inspection = api.inspect_action(self.task, action, frame.model_png, self._stop)
        except ApiStopped:
            raise
        except Exception as exc:
            self.events.log("warning", f"云端风险预检失败，使用本地规则：{exc}")
            inspection = InspectionResult(reason="云端预检不可用，已使用本地安全规则。")
        return self.safety.classify(action, self.task, inspection)

    def _check_limits(self, started: float) -> None:
        if self._stop.is_set():
            raise ApiStopped("任务已停止")
        if time.monotonic() - started > self.max_seconds:
            raise TimeoutError("任务超过最长运行时间")
        if self.store.summary and self.store.summary.action_count >= self.max_actions:
            raise TimeoutError("任务达到最大动作数量")

    def _check_window(self, *, require_foreground: bool) -> None:
        assert self.target is not None
        valid, reason = self.windows.validate(self.target, require_foreground=require_foreground)
        if not valid:
            recoverable = reason in {
                "目标窗口失去焦点",
                "目标窗口已最小化",
                "目标窗口不可见",
            }
            if not recoverable:
                raise ActionExecutionError(reason)
            self._run_gate.clear()
            self._set_state(SessionState.PAUSED, reason)
            self._wait_until_runnable()
            self.windows.activate(self.target)
            time.sleep(0.15)
            valid, reason = self.windows.validate(
                self.target, require_foreground=require_foreground
            )
            if not valid:
                raise ActionExecutionError(reason)

    def _wait_until_runnable(self) -> None:
        while not self._run_gate.wait(0.1):
            if self._stop.is_set():
                raise ApiStopped("任务已停止")
        if self._stop.is_set():
            raise ApiStopped("任务已停止")

    def _set_state(self, state: SessionState, message: str) -> None:
        with self._state_lock:
            self.state = state
        self.store.set_state(state)
        self.events.state(state, message)
        self.events.log("state", message)

    def _finish(self, state: SessionState, message: str) -> None:
        with self._state_lock:
            self.state = state
        error = message if state in {SessionState.FAILED, SessionState.TIMED_OUT} else None
        self.store.set_state(state, final_message=message, error=error)
        self.events.state(state, message)
        self.events.finished(state, message)
