from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

from .models import CaptureFrame, ComputerAction, TargetWindow
from .windows import WindowManager, user32, virtual_screen_rect

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
WHEEL_DELTA = 120


ULONG_PTR = wintypes.WPARAM


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short


VK = {
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "SHIFT": 0x10,
    "CTRL": 0x11,
    "CONTROL": 0x11,
    "ALT": 0x12,
    "OPTION": 0x12,
    "PAUSE": 0x13,
    "CAPSLOCK": 0x14,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "SPACE": 0x20,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "ARROWLEFT": 0x25,
    "UP": 0x26,
    "ARROWUP": 0x26,
    "RIGHT": 0x27,
    "ARROWRIGHT": 0x27,
    "DOWN": 0x28,
    "ARROWDOWN": 0x28,
    "DELETE": 0x2E,
    "DEL": 0x2E,
    "META": 0x5B,
    "CMD": 0x5B,
    "COMMAND": 0x5B,
}
for number in range(1, 25):
    VK[f"F{number}"] = 0x6F + number


BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "wheel": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


class ActionExecutionError(RuntimeError):
    pass


class InputExecutor:
    def __init__(self, windows: WindowManager) -> None:
        self.windows = windows
        self._lock = threading.Lock()
        self._pressed_keys: set[int] = set()
        self._pressed_buttons: set[str] = set()

    def execute(
        self,
        action: ComputerAction,
        target: TargetWindow,
        frame: CaptureFrame,
        stop_event: threading.Event,
    ) -> None:
        with self._lock:
            if stop_event.is_set():
                raise ActionExecutionError("操作已停止")
            valid, reason = self.windows.validate(target, require_foreground=True)
            if not valid:
                raise ActionExecutionError(reason)
            geometry_ok, reason = self.windows.validate_capture_geometry_for(
                target, frame.source_rect, frame.capture_hwnd
            )
            if not geometry_ok:
                raise ActionExecutionError(reason)
            self._validate_points(action, frame)

            handler = getattr(self, f"_handle_{action.type}", None)
            if handler is None:
                raise ActionExecutionError(f"不支持的动作类型: {action.type}")
            try:
                handler(action, frame, stop_event)
            except ActionExecutionError:
                raise
            except Exception as exc:
                raise ActionExecutionError(str(exc)) from exc

    def release_all(self) -> None:
        with self._lock:
            for button in tuple(self._pressed_buttons):
                try:
                    self._mouse_button(button, down=False)
                except Exception:
                    self._pressed_buttons.discard(button)
            for key in tuple(self._pressed_keys):
                try:
                    self._key_event(key, down=False)
                except Exception:
                    self._pressed_keys.discard(key)
            self._pressed_buttons.clear()
            self._pressed_keys.clear()

    @staticmethod
    def _validate_points(action: ComputerAction, frame: CaptureFrame) -> None:
        for x, y in action.model_points():
            if not frame.model_point_in_bounds(x, y):
                raise ActionExecutionError("模型动作坐标超出截图范围")
            screen_x, screen_y = frame.to_screen(x, y)
            if not frame.source_rect.contains(screen_x, screen_y):
                raise ActionExecutionError("动作坐标超出目标窗口")

    def _send(self, *items: INPUT) -> None:
        array_type = INPUT * len(items)
        sent = user32.SendInput(len(items), array_type(*items), ctypes.sizeof(INPUT))
        if sent != len(items):
            raise ctypes.WinError(ctypes.get_last_error())

    @staticmethod
    def _absolute(x: int, y: int) -> tuple[int, int]:
        virtual = virtual_screen_rect()
        width = max(1, virtual.width - 1)
        height = max(1, virtual.height - 1)
        absolute_x = round((x - virtual.left) * 65535 / width)
        absolute_y = round((y - virtual.top) * 65535 / height)
        return absolute_x, absolute_y

    def _move(self, x: int, y: int) -> None:
        absolute_x, absolute_y = self._absolute(x, y)
        self._send(
            INPUT(
                type=INPUT_MOUSE,
                mi=MOUSEINPUT(
                    absolute_x,
                    absolute_y,
                    0,
                    MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                    0,
                    0,
                ),
            )
        )

    def _mouse_button(self, button: str, *, down: bool) -> None:
        normalized = button.casefold()
        if normalized not in BUTTON_FLAGS:
            raise ActionExecutionError(f"不支持的鼠标按钮: {button}")
        flag = BUTTON_FLAGS[normalized][0 if down else 1]
        self._send(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, flag, 0, 0)))
        if down:
            self._pressed_buttons.add(normalized)
        else:
            self._pressed_buttons.discard(normalized)

    def _key_event(self, vk: int, *, down: bool) -> None:
        flags = 0 if down else KEYEVENTF_KEYUP
        self._send(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, 0, flags, 0, 0)))
        if down:
            self._pressed_keys.add(vk)
        else:
            self._pressed_keys.discard(vk)

    def _unicode_unit(self, unit: int, *, down: bool) -> None:
        flags = KEYEVENTF_UNICODE | (0 if down else KEYEVENTF_KEYUP)
        self._send(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, unit, flags, 0, 0)))

    def _resolve_vk(self, key: str) -> tuple[int, bool]:
        normalized = key.upper()
        if normalized in VK:
            return VK[normalized], False
        if len(key) == 1:
            encoded = int(user32.VkKeyScanW(key))
            if encoded == -1:
                raise ActionExecutionError(f"无法映射按键: {key}")
            return encoded & 0xFF, bool((encoded >> 8) & 1)
        raise ActionExecutionError(f"不支持的按键: {key}")

    def _with_mouse_modifiers(self, keys: tuple[str, ...], callback: Callable[[], None]) -> None:
        pressed: list[int] = []
        try:
            for name in keys:
                vk, needs_shift = self._resolve_vk(name)
                if needs_shift and VK["SHIFT"] not in pressed:
                    self._key_event(VK["SHIFT"], down=True)
                    pressed.append(VK["SHIFT"])
                self._key_event(vk, down=True)
                pressed.append(vk)
            callback()
        finally:
            for vk in reversed(pressed):
                self._key_event(vk, down=False)

    @staticmethod
    def _screen_point(action: ComputerAction, frame: CaptureFrame) -> tuple[int, int]:
        if action.x is None or action.y is None:
            raise ActionExecutionError(f"{action.type} 动作缺少坐标")
        return frame.to_screen(action.x, action.y)

    def _handle_click(
        self, action: ComputerAction, frame: CaptureFrame, _stop: threading.Event
    ) -> None:
        x, y = self._screen_point(action, frame)

        def click() -> None:
            self._move(x, y)
            self._mouse_button(action.button, down=True)
            self._mouse_button(action.button, down=False)

        self._with_mouse_modifiers(action.keys, click)

    def _handle_double_click(
        self, action: ComputerAction, frame: CaptureFrame, _stop: threading.Event
    ) -> None:
        x, y = self._screen_point(action, frame)

        def double_click() -> None:
            self._move(x, y)
            for _ in range(2):
                self._mouse_button(action.button, down=True)
                self._mouse_button(action.button, down=False)
                time.sleep(0.08)

        self._with_mouse_modifiers(action.keys, double_click)

    def _handle_move(
        self, action: ComputerAction, frame: CaptureFrame, _stop: threading.Event
    ) -> None:
        x, y = self._screen_point(action, frame)
        self._with_mouse_modifiers(action.keys, lambda: self._move(x, y))

    def _handle_scroll(
        self, action: ComputerAction, frame: CaptureFrame, _stop: threading.Event
    ) -> None:
        x, y = self._screen_point(action, frame)

        def scroll() -> None:
            self._move(x, y)
            vertical = round(-action.scroll_y / 100 * WHEEL_DELTA)
            horizontal = round(action.scroll_x / 100 * WHEEL_DELTA)
            if vertical:
                self._send(
                    INPUT(
                        type=INPUT_MOUSE,
                        mi=MOUSEINPUT(0, 0, vertical & 0xFFFFFFFF, MOUSEEVENTF_WHEEL, 0, 0),
                    )
                )
            if horizontal:
                self._send(
                    INPUT(
                        type=INPUT_MOUSE,
                        mi=MOUSEINPUT(0, 0, horizontal & 0xFFFFFFFF, MOUSEEVENTF_HWHEEL, 0, 0),
                    )
                )

        self._with_mouse_modifiers(action.keys, scroll)

    def _handle_drag(
        self, action: ComputerAction, frame: CaptureFrame, stop: threading.Event
    ) -> None:
        if len(action.path) < 2:
            raise ActionExecutionError("拖拽路径至少需要两个点")
        screen_path = [frame.to_screen(x, y) for x, y in action.path]

        def drag() -> None:
            self._move(*screen_path[0])
            self._mouse_button(action.button, down=True)
            try:
                for point in screen_path[1:]:
                    if stop.is_set():
                        raise ActionExecutionError("拖拽已被停止")
                    self._move(*point)
                    time.sleep(0.02)
            finally:
                self._mouse_button(action.button, down=False)

        self._with_mouse_modifiers(action.keys, drag)

    def _handle_keypress(
        self, action: ComputerAction, _frame: CaptureFrame, stop: threading.Event
    ) -> None:
        modifiers: list[int] = []
        regular: list[tuple[int, bool]] = []
        for key in action.keys:
            vk, needs_shift = self._resolve_vk(key)
            if vk in {VK["CTRL"], VK["SHIFT"], VK["ALT"], VK["META"]}:
                modifiers.append(vk)
            else:
                regular.append((vk, needs_shift))
        try:
            for vk in modifiers:
                self._key_event(vk, down=True)
            for vk, needs_shift in regular:
                if stop.is_set():
                    raise ActionExecutionError("键盘操作已停止")
                temporary_shift = needs_shift and VK["SHIFT"] not in modifiers
                if temporary_shift:
                    self._key_event(VK["SHIFT"], down=True)
                self._key_event(vk, down=True)
                self._key_event(vk, down=False)
                if temporary_shift:
                    self._key_event(VK["SHIFT"], down=False)
        finally:
            for vk in reversed(modifiers):
                self._key_event(vk, down=False)

    def _handle_type(
        self, action: ComputerAction, _frame: CaptureFrame, stop: threading.Event
    ) -> None:
        encoded = action.text.encode("utf-16-le")
        for index in range(0, len(encoded), 2):
            if stop.is_set():
                raise ActionExecutionError("文本输入已停止")
            unit = int.from_bytes(encoded[index : index + 2], "little")
            self._unicode_unit(unit, down=True)
            self._unicode_unit(unit, down=False)

    @staticmethod
    def _handle_wait(_action: ComputerAction, _frame: CaptureFrame, stop: threading.Event) -> None:
        if stop.wait(2.0):
            raise ActionExecutionError("等待已被停止")

    @staticmethod
    def _handle_screenshot(
        _action: ComputerAction, _frame: CaptureFrame, _stop: threading.Event
    ) -> None:
        return
