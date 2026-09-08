from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
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
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .api import ComputerAgentClient, DualModelClient, NativeComputerClient
from .capture import CaptureService
from .config import ApiKeyStore, AppConfig, is_openai_base_url
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


class LiveViewport(QFrame):
    """A supervised live view with an in-panel action preview."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("LiveViewport")
        self.setMinimumSize(520, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._pixmap = QPixmap()
        self._frame: CaptureFrame | None = None
        self._proposal: ActionProposal | None = None
        self._status = "等待绑定目标窗口"

    def set_frame(self, frame: CaptureFrame) -> None:
        if frame.model_path:
            self._pixmap = QPixmap(str(frame.model_path))
        self._frame = frame
        self.update()

    def set_proposal(self, proposal: ActionProposal | None) -> None:
        self._proposal = proposal
        self.update()

    def set_status(self, status: str) -> None:
        self._status = status
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = self.rect().adjusted(18, 18, -18, -18)
        if self._pixmap.isNull():
            painter.setPen(QColor("#737986"))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, self._status)
            return

        scaled = self._pixmap.scaled(
            bounds.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        image_rect = QRect(
            bounds.center().x() - scaled.width() // 2,
            bounds.center().y() - scaled.height() // 2,
            scaled.width(),
            scaled.height(),
        )
        painter.drawPixmap(image_rect, scaled)
        painter.setPen(QPen(QColor("#343740"), 1))
        painter.drawRect(image_rect)

        badge = QRect(image_rect.left() + 14, image_rect.top() + 14, 116, 30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 10, 14, 218))
        painter.drawRoundedRect(badge, 15, 15)
        painter.setBrush(QColor("#52d6a3"))
        painter.drawEllipse(badge.left() + 12, badge.center().y() - 4, 8, 8)
        painter.setPen(QColor("#eef1f6"))
        painter.drawText(
            badge.adjusted(28, 0, -8, 0),
            Qt.AlignmentFlag.AlignVCenter,
            "LIVE VIEW",
        )

        if not self._proposal or not self._frame:
            return
        points = self._proposal.action.model_points()
        mapped = [
            QPoint(
                image_rect.left() + round(float(x) * image_rect.width() / self._frame.model_width),
                image_rect.top() + round(float(y) * image_rect.height() / self._frame.model_height),
            )
            for x, y in points
        ]
        if self._proposal.action.type == "drag" and len(mapped) >= 2:
            painter.setPen(QPen(QColor(255, 180, 76, 225), 4))
            for start, end in pairwise(mapped):
                painter.drawLine(start, end)
        painter.setPen(QPen(QColor(255, 99, 122, 240), 4))
        for point in mapped:
            painter.drawEllipse(point, 13, 13)
            painter.drawLine(point.x() - 19, point.y(), point.x() + 19, point.y())
            painter.drawLine(point.x(), point.y() - 19, point.x(), point.y() + 19)


class ActivityTimeline(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ActivityTimeline")
        self.setAlternatingRowColors(False)
        self.setWordWrap(True)
        self.setSpacing(4)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def add_event(self, level: str, message: str) -> None:
        palette = {
            "warning": "#ffc56e",
            "error": "#ff7d91",
            "state": "#8eb9ff",
            "success": "#70dfa9",
        }
        timestamp = datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem(f"{timestamp}   {message}")
        item.setForeground(QColor(palette.get(level, "#b6bac5")))
        item.setToolTip(message)
        self.addItem(item)
        while self.count() > 200:
            self.takeItem(0)
        self.scrollToBottom()


class CyberbodyWindow(QMainWindow):
    def __init__(self, initial_task: str = "") -> None:
        super().__init__()
        self.setWindowTitle("cyberbody · Agent Workspace")
        self.setMinimumSize(1040, 700)
        self.resize(1320, 820)
        self.config = AppConfig.load()
        self.computer_api_key = ApiKeyStore.get(
            "computer",
            self.config.computer_base_url,
            include_openai_fallback=is_openai_base_url(self.config.computer_base_url),
        )
        self.vision_api_key = ApiKeyStore.get(
            "vision",
            self.config.vision_base_url,
            include_openai_fallback=is_openai_base_url(self.config.vision_base_url),
        )
        self.action_api_key = ApiKeyStore.get(
            "action",
            self.config.action_base_url,
            include_openai_fallback=is_openai_base_url(self.config.action_base_url),
        )
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

        def api_factory(callback: Callable[[str], None]) -> ComputerAgentClient:
            if self.config.execution_mode == "native":
                return NativeComputerClient(
                    self.computer_api_key or "",
                    model=self.config.computer_model,
                    base_url=self.config.computer_base_url,
                    timeout_seconds=self.config.api_timeout_seconds,
                    retries=self.config.api_retries,
                    status_callback=callback,
                )
            return DualModelClient(
                self.vision_api_key or "",
                self.action_api_key or "",
                vision_model=self.config.vision_model,
                action_model=self.config.action_model,
                vision_base_url=self.config.vision_base_url,
                action_base_url=self.config.action_base_url,
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
        central.setObjectName("AppRoot")
        page = QVBoxLayout(central)
        page.setContentsMargins(20, 16, 20, 20)
        page.setSpacing(14)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        brand.setSpacing(1)
        title = QLabel("CYBERBODY")
        title.setObjectName("Brand")
        subtitle = QLabel("Supervised computer agent workspace")
        subtitle.setObjectName("Muted")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch()
        self.state_badge = QLabel("空闲")
        self.state_badge.setObjectName("StateBadge")
        self.step_label = QLabel("0 个动作  ·  0 轮观察")
        self.step_label.setObjectName("HeaderMeta")
        self.api_label = QLabel(self._api_status_text())
        self.api_label.setObjectName("HeaderMeta")
        header.addWidget(self.step_label)
        header.addWidget(self.api_label)
        header.addWidget(self.state_badge)
        page.addLayout(header)

        outer = QSplitter(Qt.Orientation.Horizontal)
        outer.setChildrenCollapsible(False)

        control_panel = QFrame()
        control_panel.setObjectName("ControlPanel")
        control_panel.setMinimumWidth(330)
        control_panel.setMaximumWidth(410)
        controls = QVBoxLayout(control_panel)
        controls.setContentsMargins(18, 18, 18, 18)
        controls.setSpacing(12)

        controls.addWidget(self._section_label("执行引擎"))
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("ModeSelector")
        self.mode_combo.addItem("原生 Computer Use · 推荐", "native")
        self.mode_combo.addItem("双模型兼容 · Vision + Text", "dual")
        mode_index = self.mode_combo.findData(self.config.execution_mode)
        self.mode_combo.setCurrentIndex(max(0, mode_index))
        controls.addWidget(self.mode_combo)
        self.mode_description = QLabel()
        self.mode_description.setObjectName("Muted")
        self.mode_description.setWordWrap(True)
        controls.addWidget(self.mode_description)

        controls.addWidget(self._section_label("目标窗口"))
        window_row = QHBoxLayout()
        self.window_combo = QComboBox()
        self.window_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setObjectName("Quiet")
        self.bind_button = QPushButton("绑定")
        window_row.addWidget(self.window_combo, 1)
        window_row.addWidget(self.refresh_button)
        window_row.addWidget(self.bind_button)
        controls.addLayout(window_row)
        self.pick_button = QPushButton("⌖  在桌面上选择窗口")
        self.pick_button.setObjectName("Secondary")
        controls.addWidget(self.pick_button)
        self.target_label = QLabel("尚未绑定窗口")
        self.target_label.setObjectName("TargetCard")
        self.target_label.setWordWrap(True)
        controls.addWidget(self.target_label)

        controls.addWidget(self._section_label("任务"))
        self.task_edit = QTextEdit()
        self.task_edit.setPlaceholderText(
            "描述最终结果和边界。例如：在当前窗口搜索“季度报告”，打开第一条结果，但不要发送或删除任何内容。"
        )
        self.task_edit.setPlainText(initial_task)
        self.task_edit.setMinimumHeight(108)
        self.task_edit.setMaximumHeight(150)
        controls.addWidget(self.task_edit)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("▶  开始运行")
        self.start_button.setObjectName("Primary")
        self.pause_button = QPushButton("暂停")
        self.resume_button = QPushButton("继续")
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("Danger")
        action_row.addWidget(self.start_button, 2)
        action_row.addWidget(self.pause_button)
        action_row.addWidget(self.resume_button)
        action_row.addWidget(self.stop_button)
        controls.addLayout(action_row)

        controls.addWidget(self._section_label("模型连接"))
        self.settings_stack = QStackedWidget()

        native_page = QWidget()
        native_layout = QVBoxLayout(native_page)
        native_layout.setContentsMargins(0, 0, 0, 0)
        native_layout.setSpacing(8)
        computer_model_row = QHBoxLayout()
        self.computer_model_edit = QLineEdit(self.config.computer_model)
        self.computer_model_edit.setPlaceholderText("例如 gpt-5.6-sol")
        self.computer_key_button = QPushButton("设置密钥")
        computer_model_row.addWidget(self.computer_model_edit, 1)
        computer_model_row.addWidget(self.computer_key_button)
        native_layout.addLayout(computer_model_row)
        self.computer_url_edit = QLineEdit(self.config.computer_base_url)
        self.computer_url_edit.setPlaceholderText("Computer API 地址（留空使用 OpenAI）")
        native_layout.addWidget(self.computer_url_edit)
        native_note = QLabel("模型必须支持 Responses API 的正式版 computer 工具。")
        native_note.setObjectName("Muted")
        native_note.setWordWrap(True)
        native_layout.addWidget(native_note)
        self.settings_stack.addWidget(native_page)

        dual_page = QWidget()
        dual_layout = QVBoxLayout(dual_page)
        dual_layout.setContentsMargins(0, 0, 0, 0)
        dual_layout.setSpacing(8)

        vision_model_row = QHBoxLayout()
        self.vision_model_edit = QLineEdit(self.config.vision_model)
        self.vision_model_edit.setPlaceholderText("视觉模型 · 必须支持图片")
        self.vision_key_button = QPushButton("视觉密钥")
        vision_model_row.addWidget(self.vision_model_edit, 1)
        vision_model_row.addWidget(self.vision_key_button)
        dual_layout.addLayout(vision_model_row)
        self.vision_url_edit = QLineEdit(self.config.vision_base_url)
        self.vision_url_edit.setPlaceholderText("视觉 API 地址（留空使用 OpenAI）")
        dual_layout.addWidget(self.vision_url_edit)

        action_model_row = QHBoxLayout()
        self.action_model_edit = QLineEdit(self.config.action_model)
        self.action_model_edit.setPlaceholderText("操作模型 · 可以是纯文本模型")
        self.action_key_button = QPushButton("操作密钥")
        action_model_row.addWidget(self.action_model_edit, 1)
        action_model_row.addWidget(self.action_key_button)
        dual_layout.addLayout(action_model_row)
        self.action_url_edit = QLineEdit(self.config.action_base_url)
        self.action_url_edit.setPlaceholderText("操作 API 地址（留空使用 OpenAI）")
        dual_layout.addWidget(self.action_url_edit)
        self.settings_stack.addWidget(dual_page)
        controls.addWidget(self.settings_stack)
        controls.addStretch()

        emergency = QLabel("紧急停止  Ctrl + Shift + F12")
        emergency.setObjectName("EmergencyHint")
        emergency.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls.addWidget(emergency)
        outer.addWidget(control_panel)

        workspace = QFrame()
        workspace.setObjectName("Workspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(18, 18, 18, 18)
        workspace_layout.setSpacing(12)

        workspace_header = QHBoxLayout()
        workspace_titles = QVBoxLayout()
        workspace_titles.setSpacing(1)
        workspace_title = QLabel("Live workspace")
        workspace_title.setObjectName("WorkspaceTitle")
        workspace_subtitle = QLabel("每一步都可见、可暂停、可接管")
        workspace_subtitle.setObjectName("Muted")
        workspace_titles.addWidget(workspace_title)
        workspace_titles.addWidget(workspace_subtitle)
        workspace_header.addLayout(workspace_titles)
        workspace_header.addStretch()
        self.engine_badge = QLabel()
        self.engine_badge.setObjectName("EngineBadge")
        workspace_header.addWidget(self.engine_badge)
        workspace_layout.addLayout(workspace_header)

        content = QSplitter(Qt.Orientation.Horizontal)
        content.setChildrenCollapsible(False)
        live_column = QFrame()
        live_column.setObjectName("LiveColumn")
        live_layout = QVBoxLayout(live_column)
        live_layout.setContentsMargins(0, 0, 0, 0)
        live_layout.setSpacing(10)
        self.viewport = LiveViewport()
        live_layout.addWidget(self.viewport, 1)

        self.current_action = QLabel("等待任务。绑定一个普通权限窗口，然后描述目标结果。")
        self.current_action.setWordWrap(True)
        self.current_action.setObjectName("CurrentAction")
        live_layout.addWidget(self.current_action)

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
        live_layout.addWidget(self.confirm_frame)
        content.addWidget(live_column)

        activity_panel = QFrame()
        activity_panel.setObjectName("ActivityPanel")
        activity_panel.setMinimumWidth(260)
        activity_panel.setMaximumWidth(360)
        activity_layout = QVBoxLayout(activity_panel)
        activity_layout.setContentsMargins(14, 14, 14, 14)
        activity_layout.setSpacing(10)
        activity_title = QLabel("Activity")
        activity_title.setObjectName("PanelTitle")
        activity_layout.addWidget(activity_title)
        activity_hint = QLabel("状态、观察和安全裁决会记录在这里")
        activity_hint.setObjectName("Muted")
        activity_hint.setWordWrap(True)
        activity_layout.addWidget(activity_hint)
        self.activity = ActivityTimeline()
        activity_layout.addWidget(self.activity, 1)
        self.export_button = QPushButton("导出本次会话")
        self.clear_button = QPushButton("清除全部留档")
        activity_layout.addWidget(self.export_button)
        activity_layout.addWidget(self.clear_button)
        content.addWidget(activity_panel)
        content.setSizes([720, 290])
        workspace_layout.addWidget(content, 1)
        outer.addWidget(workspace)
        outer.setStretchFactor(0, 0)
        outer.setStretchFactor(1, 1)
        outer.setSizes([360, 920])
        page.addWidget(outer, 1)

        self.setCentralWidget(central)
        self.setStyleSheet(
            """
            QMainWindow, QWidget#AppRoot { background: #0b0c0f; color: #eceef3; font-size: 13px; }
            QWidget { font-family: "Segoe UI"; }
            QLabel#Brand { color: #f7f8fb; font-size: 21px; font-weight: 800; letter-spacing: 2px; }
            QLabel#Muted, QLabel#HeaderMeta { color: #858b98; }
            QLabel#HeaderMeta { padding: 0 7px; }
            QLabel#StateBadge { background: #17372d; color: #72e4b2; border: 1px solid #285946; border-radius: 14px; padding: 6px 12px; font-weight: 700; }
            QFrame#ControlPanel, QFrame#Workspace { background: #121318; border: 1px solid #24262e; border-radius: 14px; }
            QFrame#ActivityPanel { background: #0f1014; border: 1px solid #24262e; border-radius: 11px; }
            QLabel#WorkspaceTitle { font-size: 19px; font-weight: 750; }
            QLabel#PanelTitle { font-size: 15px; font-weight: 700; }
            QLabel#EngineBadge { background: #25213a; color: #b9a9ff; border: 1px solid #443a71; border-radius: 12px; padding: 5px 10px; }
            QLabel#TargetCard { background: #0e0f13; color: #afb4c0; border: 1px solid #272a32; border-radius: 9px; padding: 10px; }
            QLabel#CurrentAction { background: #171921; border: 1px solid #2b2e39; border-radius: 10px; padding: 12px; color: #dfe2e9; }
            QLabel#EmergencyHint { color: #ef9aa8; background: #23161a; border: 1px solid #4f2931; border-radius: 8px; padding: 8px; }
            QFrame#LiveViewport { background: #090a0d; border: 1px solid #2b2d35; border-radius: 11px; }
            QLineEdit, QTextEdit, QComboBox { background: #0d0e12; color: #edf0f5; border: 1px solid #30333d; border-radius: 8px; padding: 8px; selection-background-color: #7258d8; }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border-color: #7c67d9; }
            QComboBox#ModeSelector { background: #1b1828; border-color: #3e365d; font-weight: 650; }
            QPushButton { background: #1c1e25; color: #e4e6eb; border: 1px solid #343741; border-radius: 8px; padding: 8px 11px; }
            QPushButton:hover { background: #292c35; border-color: #4a4e5b; }
            QPushButton:pressed { background: #15161b; }
            QPushButton:disabled { color: #5d616c; background: #15161a; border-color: #24262c; }
            QPushButton#Primary { background: #7a5ee6; border-color: #9079ef; color: white; font-weight: 750; }
            QPushButton#Primary:hover { background: #886eed; }
            QPushButton#Secondary { background: #171922; border-color: #36394a; }
            QPushButton#Quiet { padding-left: 7px; padding-right: 7px; }
            QPushButton#Danger { color: #ff9baa; background: #24171b; border-color: #553039; }
            QFrame#ConfirmCard { background: #2a2113; border: 1px solid #7d5924; border-radius: 10px; }
            QLabel#ConfirmTitle { color: #ffd38a; font-size: 15px; font-weight: 750; }
            QListWidget#ActivityTimeline { background: transparent; border: 0; outline: 0; }
            QListWidget#ActivityTimeline::item { background: #15161b; border: 1px solid #24262e; border-radius: 7px; padding: 8px; margin-bottom: 2px; }
            QListWidget#ActivityTimeline::item:selected { background: #232033; border-color: #4a416d; }
            QSplitter::handle { background: transparent; width: 8px; }
            QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
            QScrollBar::handle:vertical { background: #353843; border-radius: 4px; min-height: 24px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """
        )
        self._sync_mode_ui()
        self._update_buttons()

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #8e94a2; margin-top: 3px;"
            "letter-spacing: 1px;"
        )
        return label

    def _connect_signals(self) -> None:
        self.mode_combo.currentIndexChanged.connect(self._sync_mode_ui)
        self.refresh_button.clicked.connect(self.refresh_windows)
        self.bind_button.clicked.connect(self.bind_selected_window)
        self.pick_button.clicked.connect(self.start_picker)
        self.start_button.clicked.connect(self.start_task)
        self.pause_button.clicked.connect(self.controller.pause)
        self.resume_button.clicked.connect(self.controller.resume)
        self.stop_button.clicked.connect(self.emergency_stop)
        self.computer_key_button.clicked.connect(lambda: self.configure_api_key("computer"))
        self.vision_key_button.clicked.connect(lambda: self.configure_api_key("vision"))
        self.action_key_button.clicked.connect(lambda: self.configure_api_key("action"))
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

    def _sync_mode_ui(self) -> None:
        mode = str(self.mode_combo.currentData() or "native")
        native = mode == "native"
        self.settings_stack.setCurrentIndex(0 if native else 1)
        self.mode_description.setText(
            "一个支持 computer 工具的模型持续观察、规划和自我校正。"
            if native
            else "视觉模型读取截图，纯文本模型根据结构化观察规划动作。"
        )
        self.engine_badge.setText("NATIVE COMPUTER" if native else "DUAL MODEL")
        self.api_label.setText(self._api_status_text())

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
        self.viewport.set_status("目标窗口已绑定，等待开始任务")
        self.on_log("info", f"已绑定窗口：{self.target.title}")
        self._update_buttons()

    def configure_api_key(self, role: str) -> None:
        labels = {"computer": "Computer", "vision": "视觉", "action": "操作"}
        label = labels[role]
        base_urls = {
            "computer": self.computer_url_edit.text().strip(),
            "vision": self.vision_url_edit.text().strip(),
            "action": self.action_url_edit.text().strip(),
        }
        base_url = base_urls[role]
        value, accepted = QInputDialog.getText(
            self,
            f"设置{label} API 密钥",
            f"密钥仅用于{label}接口，并保存到 Windows 凭据管理器；不会写入配置或日志。",
            QLineEdit.EchoMode.Password,
        )
        if not accepted or not value.strip():
            return
        try:
            ApiKeyStore.set(role, value, base_url)
            if role == "computer":
                self.computer_api_key = value.strip()
            elif role == "vision":
                self.vision_api_key = value.strip()
            else:
                self.action_api_key = value.strip()
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.api_label.setText(self._api_status_text())
        self.on_log("info", f"{label} API 密钥已安全保存")

    def start_task(self) -> None:
        if self.target is None:
            QMessageBox.warning(self, "尚未绑定", "请先绑定一个目标窗口。")
            return
        task = self.task_edit.toPlainText().strip()
        if not task:
            QMessageBox.warning(self, "任务为空", "请输入自然语言任务。")
            return
        mode = str(self.mode_combo.currentData() or "native")
        computer_model = self.computer_model_edit.text().strip() or "gpt-5.6-sol"
        computer_base_url = self.computer_url_edit.text().strip()
        vision_model = self.vision_model_edit.text().strip() or "gpt-5.6"
        action_model = self.action_model_edit.text().strip() or "gpt-5.6"
        vision_base_url = self.vision_url_edit.text().strip()
        action_base_url = self.action_url_edit.text().strip()
        self.config.execution_mode = mode
        self.config.computer_model = computer_model
        self.config.computer_base_url = computer_base_url
        self.config.vision_model = vision_model
        self.config.action_model = action_model
        self.config.vision_base_url = vision_base_url
        self.config.action_base_url = action_base_url
        try:
            self.config.validate()
        except ValueError as exc:
            QMessageBox.critical(self, "模型接口配置无效", str(exc))
            return
        if mode == "native":
            self.computer_api_key = ApiKeyStore.get(
                "computer",
                computer_base_url,
                include_openai_fallback=is_openai_base_url(computer_base_url),
            )
            if not self.computer_api_key:
                self.configure_api_key("computer")
                if not self.computer_api_key:
                    return
        else:
            self.vision_api_key = ApiKeyStore.get(
                "vision",
                vision_base_url,
                include_openai_fallback=is_openai_base_url(vision_base_url),
            )
            self.action_api_key = ApiKeyStore.get(
                "action",
                action_base_url,
                include_openai_fallback=is_openai_base_url(action_base_url),
            )
            if not self.vision_api_key:
                self.configure_api_key("vision")
                if not self.vision_api_key:
                    return
            if not self.action_api_key:
                self.configure_api_key("action")
                if not self.action_api_key:
                    return
        try:
            self.config.save()
            if mode == "native":
                self.controller.start(
                    task,
                    self.target,
                    computer_model,
                    computer_model,
                    execution_mode=mode,
                )
            else:
                self.controller.start(
                    task,
                    self.target,
                    vision_model,
                    action_model,
                    execution_mode=mode,
                )
        except Exception as exc:
            QMessageBox.critical(self, "无法开始任务", str(exc))
            return
        model_summary = (
            f"Computer 模型：{computer_model}"
            if mode == "native"
            else f"视觉模型：{vision_model}；操作模型：{action_model}"
        )
        self.on_log("info", f"任务已开始，{model_summary}")
        self._update_buttons()

    def _api_status_text(self) -> str:
        mode_combo = getattr(self, "mode_combo", None)
        mode = (
            str(mode_combo.currentData()) if mode_combo is not None else self.config.execution_mode
        )
        if mode == "native":
            computer = "已配置" if self.computer_api_key else "未配置"
            return f"Computer API {computer}"
        vision = "已配置" if self.vision_api_key else "未配置"
        action = "已配置" if self.action_api_key else "未配置"
        return f"API：视觉 {vision} · 操作 {action}"

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
        self.viewport.set_status(message)
        if state_value in {"executing", "observing", "completed", "failed", "stopped", "timed_out"}:
            self.overlay.hide()
        if state_value in {"observing", "completed", "failed", "stopped", "timed_out"}:
            self.viewport.set_proposal(None)
        if self.store.summary:
            self.step_label.setText(
                f"{self.store.summary.action_count} 个动作  ·  "
                f"{self.store.summary.round_count} 轮观察"
            )
        self._update_buttons()

    def on_log(self, level: str, message: str) -> None:
        self.activity.add_event(level, message)

    def on_frame(self, frame: CaptureFrame) -> None:
        self.viewport.set_frame(frame)
        if self.store.summary:
            self.step_label.setText(
                f"{self.store.summary.action_count} 个动作  ·  "
                f"{self.store.summary.round_count} 轮观察"
            )

    def on_proposal(self, proposal: ActionProposal, frame: CaptureFrame) -> None:
        self.current_action.setText(
            f"{proposal.purpose}\n目标：{proposal.target_label}\n裁决：{proposal.decision.value}"
        )
        self.viewport.set_proposal(proposal)
        self.overlay.show_proposal(proposal, frame)

    def on_finished(self, state: str, message: str) -> None:
        self.overlay.hide()
        self.confirm_frame.hide()
        self.confirmation = None
        self.viewport.set_proposal(None)
        self.viewport.set_status(message)
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
        self.mode_combo.setEnabled(not running)
        self.settings_stack.setEnabled(not running)
        self.window_combo.setEnabled(not running)
        self.bind_button.setEnabled(not running)
        self.pick_button.setEnabled(not running)

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
