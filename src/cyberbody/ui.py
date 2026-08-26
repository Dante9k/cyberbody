from __future__ import annotations

import html
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .api import OpenAIComputerClient
from .capture import CaptureService
from .config import ApiKeyStore, AppConfig
from .controller import AutomationController, ControllerEvents
from .input import InputExecutor
from .ipc import LocalCommandServer
from .models import ActionProposal, CaptureFrame, SessionState, TargetWindow
from .safety import SafetyGate
from .storage import SessionStore
from .windows import (
    WindowManager,
    emergency_hotkey_pressed,
    exclude_window_from_capture,
    virtual_screen_rect,
)


@dataclass(slots=True)
class ConfirmationRequest:
    proposal: ActionProposal
    handoff: bool
    event: threading.Event
    approved: bool = False

    def resolve(self, approved: bool) -> None:
        self.approved = approved
        self.event.set()


class UiBridge(QObject):
    state_changed = Signal(str, str)
    log_added = Signal(str, str)
    frame_ready = Signal(object)
    proposal_ready = Signal(object, object)
    confirmation_requested = Signal(object)
    finished = Signal(str, str)
    api_status = Signal(str)


class ActionOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        virtual = virtual_screen_rect()
        self.setGeometry(virtual.left, virtual.top, virtual.width, virtual.height)
        self._points: list[QPoint] = []
        self._label = ""
        self._drag = False

    def show_proposal(self, proposal: ActionProposal, frame: CaptureFrame) -> None:
        self._points = [QPoint(*frame.to_screen(x, y)) for x, y in proposal.action.model_points()]
        virtual = virtual_screen_rect()
        self._points = [
            QPoint(point.x() - virtual.left, point.y() - virtual.top) for point in self._points
        ]
        self._label = proposal.target_label or proposal.purpose
        self._drag = proposal.action.type == "drag"
        if self._points:
            self.show()
            exclude_window_from_capture(int(self.winId()))
            self.raise_()
            self.update()
        else:
            self.hide()

    def paintEvent(self, _event: QPaintEvent) -> None:
        if not self._points:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._drag and len(self._points) >= 2:
            painter.setPen(QPen(QColor(255, 170, 32, 230), 6))
            for start, end in zip(self._points, self._points[1:], strict=False):
                painter.drawLine(start, end)
        painter.setPen(QPen(QColor(255, 72, 72, 245), 5))
        for point in self._points:
            painter.drawEllipse(point, 20, 20)
            painter.drawLine(point.x() - 28, point.y(), point.x() + 28, point.y())
            painter.drawLine(point.x(), point.y() - 28, point.x(), point.y() + 28)
        anchor = self._points[0] + QPoint(26, -42)
        box = QRect(anchor, QPoint(anchor.x() + 300, anchor.y() + 34))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(15, 23, 42, 225))
        painter.drawRoundedRect(box, 8, 8)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(box.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter, self._label)


class WindowPickerOverlay(QWidget):
    selected = Signal(int)
    cancelled = Signal()

    def __init__(self, windows: WindowManager) -> None:
        super().__init__(None)
        self.windows = windows
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        virtual = virtual_screen_rect()
        self.setGeometry(virtual.left, virtual.top, virtual.width, virtual.height)
        self._cursor = QPoint(self.width() // 2, self.height() // 2)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._cursor = event.position().toPoint()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            self.close()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        global_point = event.globalPosition().toPoint()
        choice = self.windows.window_at_point(
            global_point.x(), global_point.y(), exclude_pid=os.getpid()
        )
        if choice:
            self.selected.emit(choice.hwnd)
        else:
            self.cancelled.emit()
        self.close()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(15, 23, 42, 45))
        painter.setPen(QPen(QColor(62, 207, 255, 230), 2))
        painter.drawLine(0, self._cursor.y(), self.width(), self._cursor.y())
        painter.drawLine(self._cursor.x(), 0, self._cursor.x(), self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(15, 23, 42, 235))
        box = QRect(self._cursor.x() + 20, self._cursor.y() + 20, 330, 44)
        painter.drawRoundedRect(box, 8, 8)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            box,
            Qt.AlignmentFlag.AlignCenter,
            "点击目标窗口 · 右键或 Esc 取消",
        )


class CyberbodyWindow(QMainWindow):
    def __init__(self, initial_task: str = "") -> None:
        super().__init__()
        self.setWindowTitle("cyberbody · 可视化操作监管")
        self.setMinimumSize(430, 760)
        self.resize(470, 900)
        self.config = AppConfig.load()
        self.api_key = ApiKeyStore.get()
        self.windows = WindowManager()
        self.store = SessionStore()
        SessionStore.cleanup_expired(self.config.retention_days)
        self.capture = CaptureService(
            self.windows,
            self.store,
            self.config.screenshot_max_width,
            self.config.screenshot_max_height,
        )
        self.executor = InputExecutor(self.windows)
        self.safety = SafetyGate()
        self.bridge = UiBridge()
        self.overlay = ActionOverlay()
        self.target: TargetWindow | None = None
        self.confirmation: ConfirmationRequest | None = None
        self._picker: WindowPickerOverlay | None = None

        events = ControllerEvents(
            state=lambda state, message: self.bridge.state_changed.emit(state.value, message),
            log=lambda level, message: self.bridge.log_added.emit(level, message),
            frame=lambda frame: self.bridge.frame_ready.emit(frame),
            proposal=lambda proposal, frame: self.bridge.proposal_ready.emit(proposal, frame),
            confirmation=self._ask_confirmation,
            finished=lambda state, message: self.bridge.finished.emit(state.value, message),
            api_status=lambda message: self.bridge.api_status.emit(message),
        )

        def api_factory(callback: Callable[[str], None]) -> OpenAIComputerClient:
            key = self.api_key or ApiKeyStore.get() or ""
            return OpenAIComputerClient(
                key,
                model=self.config.model,
                timeout_seconds=self.config.api_timeout_seconds,
                retries=self.config.api_retries,
                status_callback=callback,
            )

        self.controller = AutomationController(
            self.windows,
            self.store,
            self.capture,
            self.executor,
            self.safety,
            api_factory,
            events,
            max_actions=self.config.max_actions,
            max_seconds=self.config.max_seconds,
            preview_delay_ms=self.config.preview_delay_ms,
        )
        self._build_ui(initial_task)
        self._connect_signals()
        self.refresh_windows()

        self.hotkey_timer = QTimer(self)
        self.hotkey_timer.timeout.connect(self._poll_hotkey)
        self.hotkey_timer.start(60)
        self._hotkey_latched = False

        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.timeout.connect(self._cleanup_sessions)
        self.cleanup_timer.start(24 * 60 * 60 * 1000)

        self.ipc = LocalCommandServer(self.handle_command)
        if not self.ipc.listen():
            raise RuntimeError("无法启动本地单实例控制通道")

    def _build_ui(self, initial_task: str) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("cyberbody")
        title.setObjectName("Title")
        subtitle = QLabel("观察屏幕，规划动作，并在你的监管下操作")
        subtitle.setObjectName("Subtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        status_row = QHBoxLayout()
        self.state_badge = QLabel("空闲")
        self.state_badge.setObjectName("StateBadge")
        self.api_label = QLabel("API：" + ("已配置" if self.api_key else "未配置"))
        self.api_label.setObjectName("Muted")
        status_row.addWidget(self.state_badge)
        status_row.addStretch()
        status_row.addWidget(self.api_label)
        root.addLayout(status_row)

        root.addWidget(self._section_label("1. 绑定目标窗口"))
        window_row = QHBoxLayout()
        self.window_combo = QComboBox()
        self.window_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.refresh_button = QPushButton("刷新")
        self.bind_button = QPushButton("绑定")
        window_row.addWidget(self.window_combo, 1)
        window_row.addWidget(self.refresh_button)
        window_row.addWidget(self.bind_button)
        root.addLayout(window_row)
        self.pick_button = QPushButton("⌖  十字准星选择窗口")
        root.addWidget(self.pick_button)
        self.target_label = QLabel("尚未绑定窗口")
        self.target_label.setObjectName("Muted")
        self.target_label.setWordWrap(True)
        root.addWidget(self.target_label)

        root.addWidget(self._section_label("2. 描述任务"))
        self.task_edit = QTextEdit()
        self.task_edit.setPlaceholderText(
            "例如：在当前窗口搜索“季度报告”，打开第一条结果，但不要发送或删除任何内容。"
        )
        self.task_edit.setPlainText(initial_task)
        self.task_edit.setMaximumHeight(110)
        root.addWidget(self.task_edit)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("模型"))
        self.model_edit = QLineEdit(self.config.model)
        self.model_edit.setPlaceholderText("gpt-5.6")
        self.key_button = QPushButton("设置 API 密钥")
        model_row.addWidget(self.model_edit, 1)
        model_row.addWidget(self.key_button)
        root.addLayout(model_row)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("开始")
        self.start_button.setObjectName("Primary")
        self.pause_button = QPushButton("暂停")
        self.resume_button = QPushButton("继续")
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("Danger")
        action_row.addWidget(self.start_button, 2)
        action_row.addWidget(self.pause_button)
        action_row.addWidget(self.resume_button)
        action_row.addWidget(self.stop_button)
        root.addLayout(action_row)

        self.confirm_frame = QFrame()
        self.confirm_frame.setObjectName("ConfirmCard")
        confirm_layout = QVBoxLayout(self.confirm_frame)
        self.confirm_title = QLabel("需要确认")
        self.confirm_title.setObjectName("ConfirmTitle")
        self.confirm_text = QLabel("")
        self.confirm_text.setWordWrap(True)
        confirm_buttons = QHBoxLayout()
        self.approve_button = QPushButton("允许这一步")
        self.approve_button.setObjectName("Primary")
        self.reject_button = QPushButton("拒绝并停止")
        confirm_buttons.addWidget(self.approve_button)
        confirm_buttons.addWidget(self.reject_button)
        confirm_layout.addWidget(self.confirm_title)
        confirm_layout.addWidget(self.confirm_text)
        confirm_layout.addLayout(confirm_buttons)
        self.confirm_frame.hide()
        root.addWidget(self.confirm_frame)

        root.addWidget(self._section_label("3. 实时监管"))
        self.current_action = QLabel("等待任务")
        self.current_action.setWordWrap(True)
        self.current_action.setObjectName("CurrentAction")
        root.addWidget(self.current_action)
        self.preview = QLabel("截图将在这里显示")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(170)
        self.preview.setMaximumHeight(230)
        self.preview.setObjectName("Preview")
        root.addWidget(self.preview)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        root.addWidget(self.log)

        footer = QHBoxLayout()
        self.export_button = QPushButton("导出本次会话")
        self.clear_button = QPushButton("清除全部留档")
        footer.addWidget(self.export_button)
        footer.addWidget(self.clear_button)
        root.addLayout(footer)
        root.addWidget(QLabel("紧急停止：Ctrl + Shift + F12"))

        self.setCentralWidget(central)
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #0f172a; color: #e5edf8; font-size: 13px; }
            QLabel#Title { font-size: 26px; font-weight: 700; color: #f8fbff; }
            QLabel#Subtitle, QLabel#Muted { color: #91a4bd; }
            QLabel#StateBadge { background: #19324f; color: #75d7ff; border-radius: 12px; padding: 5px 10px; font-weight: 600; }
            QLabel#CurrentAction { background: #17243a; border: 1px solid #29405e; border-radius: 8px; padding: 10px; }
            QLabel#Preview { background: #0b1220; border: 1px solid #263950; border-radius: 8px; color: #6f829c; }
            QLineEdit, QTextEdit, QComboBox { background: #111d30; border: 1px solid #304761; border-radius: 6px; padding: 7px; selection-background-color: #177ddc; }
            QPushButton { background: #223651; border: 1px solid #36516f; border-radius: 6px; padding: 7px 10px; }
            QPushButton:hover { background: #2b4465; }
            QPushButton:disabled { color: #66758a; background: #172236; }
            QPushButton#Primary { background: #1473e6; border-color: #2587f4; font-weight: 600; }
            QPushButton#Danger { color: #ffb1b1; border-color: #73404b; }
            QFrame#ConfirmCard { background: #352815; border: 1px solid #a87426; border-radius: 8px; }
            QLabel#ConfirmTitle { color: #ffd68a; font-weight: 700; }
            """
        )
        self._update_buttons()

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight: 650; color: #cbd8e8; margin-top: 4px;")
        return label

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_windows)
        self.bind_button.clicked.connect(self.bind_selected_window)
        self.pick_button.clicked.connect(self.start_picker)
        self.start_button.clicked.connect(self.start_task)
        self.pause_button.clicked.connect(self.controller.pause)
        self.resume_button.clicked.connect(self.controller.resume)
        self.stop_button.clicked.connect(self.emergency_stop)
        self.key_button.clicked.connect(self.configure_api_key)
        self.export_button.clicked.connect(self.export_session)
        self.clear_button.clicked.connect(self.clear_sessions)
        self.approve_button.clicked.connect(lambda: self.resolve_confirmation(True))
        self.reject_button.clicked.connect(lambda: self.resolve_confirmation(False))

        self.bridge.state_changed.connect(self.on_state_changed)
        self.bridge.log_added.connect(self.on_log)
        self.bridge.frame_ready.connect(self.on_frame)
        self.bridge.proposal_ready.connect(self.on_proposal)
        self.bridge.confirmation_requested.connect(self.on_confirmation)
        self.bridge.finished.connect(self.on_finished)
        self.bridge.api_status.connect(self.api_label.setText)

    def refresh_windows(self) -> None:
        selected_hwnd = self.window_combo.currentData()
        self.window_combo.clear()
        for choice in self.windows.enumerate_windows(exclude_pid=os.getpid()):
            label = f"{choice.title}  ·  PID {choice.pid}"
            self.window_combo.addItem(label, choice.hwnd)
        if selected_hwnd:
            index = self.window_combo.findData(selected_hwnd)
            if index >= 0:
                self.window_combo.setCurrentIndex(index)

    def bind_selected_window(self) -> None:
        hwnd = self.window_combo.currentData()
        if not hwnd:
            QMessageBox.warning(self, "无法绑定", "请先选择一个可见窗口。")
            return
        self._bind_hwnd(int(hwnd))

    def start_picker(self) -> None:
        self._picker = WindowPickerOverlay(self.windows)
        self._picker.selected.connect(self._bind_hwnd)
        self._picker.show()
        self._picker.activateWindow()

    def _bind_hwnd(self, hwnd: int) -> None:
        try:
            self.target = self.windows.bind(hwnd)
        except Exception as exc:
            QMessageBox.critical(self, "无法绑定窗口", str(exc))
            return
        self.target_label.setText(
            f"已绑定：{self.target.title}\nPID {self.target.pid} · {self.target.client_rect.width}×{self.target.client_rect.height} · DPI {self.target.dpi}"
        )
        self.on_log("info", f"已绑定窗口：{self.target.title}")
        self._update_buttons()

    def configure_api_key(self) -> None:
        value, accepted = QInputDialog.getText(
            self,
            "设置 OpenAI API 密钥",
            "密钥将保存到 Windows 凭据管理器；不会写入配置或日志。",
            QLineEdit.EchoMode.Password,
        )
        if not accepted or not value.strip():
            return
        try:
            ApiKeyStore.set(value)
            self.api_key = value.strip()
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.api_label.setText("API：已配置")
        self.on_log("info", "OpenAI API 密钥已安全保存")

    def start_task(self) -> None:
        if self.target is None:
            QMessageBox.warning(self, "尚未绑定", "请先绑定一个目标窗口。")
            return
        if not self.api_key:
            self.configure_api_key()
            if not self.api_key:
                return
        task = self.task_edit.toPlainText().strip()
        if not task:
            QMessageBox.warning(self, "任务为空", "请输入自然语言任务。")
            return
        model = self.model_edit.text().strip() or "gpt-5.6"
        self.config.model = model
        try:
            self.config.save()
            self.controller.start(task, self.target, model)
        except Exception as exc:
            QMessageBox.critical(self, "无法开始任务", str(exc))
            return
        self.on_log("info", f"任务已开始，模型：{model}")
        self._update_buttons()

    def emergency_stop(self) -> None:
        if self.confirmation:
            self.confirmation.resolve(False)
            self.confirmation = None
        self.confirm_frame.hide()
        self.overlay.hide()
        self.controller.stop("已触发紧急停止")
        self.on_log("warning", "紧急停止已触发")
        self._update_buttons()

    def _ask_confirmation(self, proposal: ActionProposal, handoff: bool) -> bool:
        request = ConfirmationRequest(proposal, handoff, threading.Event())
        self.bridge.confirmation_requested.emit(request)
        while not request.event.wait(0.1):
            if not self.controller.is_running:
                return False
        return request.approved

    def on_confirmation(self, request: ConfirmationRequest) -> None:
        self.confirmation = request
        proposal = request.proposal
        self.confirm_title.setText("需要你接管" if request.handoff else "风险操作确认")
        self.confirm_text.setText(
            f"{proposal.purpose}\n目标：{proposal.target_label}\n风险：{proposal.risk_category.value}\n{proposal.reason}"
        )
        self.approve_button.setText("我已完成，继续" if request.handoff else "允许这一步")
        self.confirm_frame.show()
        self.raise_()

    def resolve_confirmation(self, approved: bool) -> None:
        if self.confirmation is None:
            return
        self.confirmation.resolve(approved)
        self.confirmation = None
        self.confirm_frame.hide()

    def on_state_changed(self, state_value: str, message: str) -> None:
        labels = {
            "idle": "空闲",
            "planning": "规划中",
            "previewing": "预览动作",
            "executing": "执行中",
            "observing": "观察中",
            "paused": "已暂停",
            "awaiting_confirmation": "等待确认",
            "completed": "已完成",
            "failed": "失败",
            "stopped": "已停止",
            "timed_out": "已超时",
        }
        self.state_badge.setText(labels.get(state_value, state_value))
        self.current_action.setText(message)
        if state_value in {"executing", "observing", "completed", "failed", "stopped", "timed_out"}:
            self.overlay.hide()
        self._update_buttons()

    def on_log(self, level: str, message: str) -> None:
        colors = {"warning": "#ffca7a", "error": "#ff8f8f", "state": "#7dd3fc"}
        color = colors.get(level, "#cbd5e1")
        self.log.append(f'<span style="color:{color}">{html.escape(message)}</span>')

    def on_frame(self, frame: CaptureFrame) -> None:
        if not frame.model_path:
            return
        pixmap = QPixmap(str(frame.model_path))
        self.preview.setPixmap(
            pixmap.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def on_proposal(self, proposal: ActionProposal, frame: CaptureFrame) -> None:
        self.current_action.setText(
            f"{proposal.purpose}\n目标：{proposal.target_label}\n裁决：{proposal.decision.value}"
        )
        self.overlay.show_proposal(proposal, frame)

    def on_finished(self, state: str, message: str) -> None:
        self.overlay.hide()
        self.confirm_frame.hide()
        self.confirmation = None
        self.on_log("info" if state == "completed" else "warning", message)
        self._update_buttons()
        QTimer.singleShot(250, self._update_buttons)

    def _update_buttons(self) -> None:
        running = self.controller.is_running if hasattr(self, "controller") else False
        paused = hasattr(self, "controller") and self.controller.state == SessionState.PAUSED
        self.start_button.setEnabled(not running and self.target is not None)
        self.pause_button.setEnabled(running and not paused)
        self.resume_button.setEnabled(running and paused)
        self.stop_button.setEnabled(running)

    def _poll_hotkey(self) -> None:
        pressed = emergency_hotkey_pressed()
        if pressed and not self._hotkey_latched and self.controller.is_running:
            self.emergency_stop()
        self._hotkey_latched = pressed

    def _cleanup_sessions(self) -> None:
        removed = SessionStore.cleanup_expired(self.config.retention_days)
        if removed:
            self.on_log("info", f"已清理 {len(removed)} 个过期会话")

    def export_session(self) -> None:
        if not self.store.session_dir:
            QMessageBox.information(self, "没有会话", "当前还没有可导出的会话。")
            return
        default_name = (
            f"cyberbody-{self.store.summary.session_id}.zip"
            if self.store.summary
            else "cyberbody-session.zip"
        )
        path, _ = QFileDialog.getSaveFileName(self, "导出会话", default_name, "ZIP 文件 (*.zip)")
        if path:
            try:
                self.store.export(Path(path))
                self.on_log("info", f"会话已导出：{path}")
            except Exception as exc:
                QMessageBox.critical(self, "导出失败", str(exc))

    def clear_sessions(self) -> None:
        if self.controller.is_running:
            QMessageBox.warning(self, "任务正在运行", "请先停止当前任务再清除留档。")
            return
        answer = QMessageBox.question(
            self,
            "清除全部留档",
            "这会永久删除所有本地会话日志和截图。确定继续吗？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        count = SessionStore.clear_all()
        self.store.session_dir = None
        self.store.summary = None
        self.on_log("warning", f"已删除 {count} 个本地会话")

    def handle_command(self, request: dict[str, Any]) -> dict[str, Any]:
        command = request.get("command", "status")
        if command in {"start", "show"}:
            self.show()
            self.raise_()
            self.activateWindow()
            return self.controller.status()
        if command == "run":
            task = str(request.get("task", "")).strip()
            if task:
                self.task_edit.setPlainText(task)
            self.show()
            self.raise_()
            self.activateWindow()
            return {**self.controller.status(), "task_prefilled": bool(task)}
        if command == "stop":
            self.emergency_stop()
            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(250, app.quit)
            return {"state": "stopping"}
        if command == "status":
            return self.controller.status()
        raise ValueError(f"未知命令：{command}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller.is_running:
            answer = QMessageBox.question(
                self,
                "停止并退出？",
                "当前任务仍在运行。退出会立即停止所有输入操作。",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.emergency_stop()
        self.ipc.close()
        self.overlay.close()
        event.accept()


def run_gui(initial_task: str = "") -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("cyberbody")
    app.setOrganizationName("cyberbody")
    window = CyberbodyWindow(initial_task)
    window.show()
    return app.exec()
