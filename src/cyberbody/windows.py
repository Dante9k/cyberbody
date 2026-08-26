from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

from .models import Rect, TargetWindow

if os.name != "nt":
    raise RuntimeError("cyberbody only supports Windows")


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
user32.SetProcessDPIAware.argtypes = []
user32.SetProcessDPIAware.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.ClientToScreen.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
kernel32.GetCurrentProcessId.argtypes = []
kernel32.GetCurrentProcessId.restype = wintypes.DWORD


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class TOKEN_ELEVATION_STRUCT(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


GA_ROOT = 2
GW_OWNER = 4
SW_RESTORE = 9
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def enable_per_monitor_dpi_awareness() -> None:
    context = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    if not user32.SetProcessDpiAwarenessContext(context):
        user32.SetProcessDPIAware()


enable_per_monitor_dpi_awareness()


def _last_error(message: str) -> OSError:
    code = ctypes.get_last_error()
    return OSError(code, f"{message}: {ctypes.FormatError(code)}")


def _get_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def _get_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _rect(hwnd: int) -> Rect:
    raw = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(raw)):
        raise _last_error("Unable to read window rectangle")
    return Rect(raw.left, raw.top, raw.right, raw.bottom)


def _client_rect(hwnd: int) -> Rect:
    raw = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(raw)):
        raise _last_error("Unable to read client rectangle")
    top_left = POINT(raw.left, raw.top)
    bottom_right = POINT(raw.right, raw.bottom)
    if not user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
        raise _last_error("Unable to map client origin")
    if not user32.ClientToScreen(hwnd, ctypes.byref(bottom_right)):
        raise _last_error("Unable to map client corner")
    return Rect(top_left.x, top_left.y, bottom_right.x, bottom_right.y)


def _is_cloaked(hwnd: int) -> bool:
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        cloaked = wintypes.DWORD()
        result = dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
        return result == 0 and bool(cloaked.value)
    except Exception:
        return False


def _process_is_elevated(pid: int) -> bool:
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return True  # Access denied is treated conservatively as a higher-integrity target.
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return True
        elevation = TOKEN_ELEVATION_STRUCT()
        returned = wintypes.DWORD()
        if not advapi32.GetTokenInformation(
            token,
            TOKEN_ELEVATION,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(returned),
        ):
            return True
        return bool(elevation.TokenIsElevated)
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(process)


@dataclass(frozen=True, slots=True)
class WindowChoice:
    hwnd: int
    pid: int
    title: str
    rect: Rect


class WindowManager:
    def enumerate_windows(self, exclude_pid: int | None = None) -> list[WindowChoice]:
        choices: list[WindowChoice] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            title = _get_title(hwnd).strip()
            pid = _get_pid(hwnd)
            if not title or (exclude_pid is not None and pid == exclude_pid) or _is_cloaked(hwnd):
                return True
            try:
                bounds = _rect(hwnd)
            except OSError:
                return True
            if bounds.width < 100 or bounds.height < 60:
                return True
            choices.append(WindowChoice(int(hwnd), pid, title, bounds))
            return True

        user32.EnumWindows(callback, 0)
        return choices

    def window_at_point(
        self, x: int, y: int, exclude_pid: int | None = None
    ) -> WindowChoice | None:
        for choice in self.enumerate_windows(exclude_pid=exclude_pid):
            if choice.rect.contains(x, y):
                return choice
        return None

    def bind(self, hwnd: int) -> TargetWindow:
        root = int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)
        if not user32.IsWindow(root):
            raise ValueError("所选窗口已经不存在")
        target_pid = _get_pid(root)
        current_pid = int(kernel32.GetCurrentProcessId())
        if _process_is_elevated(target_pid) and not _process_is_elevated(current_pid):
            raise ValueError("不能绑定管理员权限窗口；请改用普通权限目标窗口")
        title = _get_title(root).strip() or f"窗口 {root}"
        dpi = int(user32.GetDpiForWindow(root) or 96)
        target = TargetWindow(
            hwnd=root,
            pid=target_pid,
            title=title,
            window_rect=_rect(root),
            client_rect=_client_rect(root),
            dpi=dpi,
            allowed_owned_hwnds={root},
        )
        if target.client_rect.width <= 0 or target.client_rect.height <= 0:
            raise ValueError("所选窗口没有可捕获的客户区")
        return target

    def refresh(self, target: TargetWindow) -> TargetWindow:
        if not user32.IsWindow(target.hwnd):
            raise RuntimeError("目标窗口已经关闭")
        target.title = _get_title(target.hwnd).strip() or target.title
        target.window_rect = _rect(target.hwnd)
        target.client_rect = _client_rect(target.hwnd)
        target.dpi = int(user32.GetDpiForWindow(target.hwnd) or target.dpi)
        self.refresh_owned_windows(target)
        return target

    def refresh_owned_windows(self, target: TargetWindow) -> None:
        allowed = {target.hwnd}
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            if _get_pid(hwnd) != target.pid:
                return True
            owner = int(user32.GetWindow(hwnd, GW_OWNER) or 0)
            visited: set[int] = set()
            while owner and owner not in visited:
                if owner == target.hwnd:
                    allowed.add(int(hwnd))
                    break
                visited.add(owner)
                owner = int(user32.GetWindow(owner, GW_OWNER) or 0)
            return True

        user32.EnumWindows(callback, 0)
        target.allowed_owned_hwnds = allowed

    def is_allowed_window(self, target: TargetWindow, hwnd: int) -> bool:
        if not hwnd:
            return False
        self.refresh_owned_windows(target)
        return int(hwnd) in target.allowed_owned_hwnds

    def validate(
        self, target: TargetWindow, *, require_foreground: bool = True
    ) -> tuple[bool, str]:
        if not user32.IsWindow(target.hwnd):
            return False, "目标窗口已经关闭"
        if not user32.IsWindowVisible(target.hwnd):
            return False, "目标窗口不可见"
        if user32.IsIconic(target.hwnd):
            return False, "目标窗口已最小化"
        try:
            current_pid = _get_pid(target.hwnd)
        except Exception:
            return False, "无法读取目标窗口进程"
        if current_pid != target.pid:
            return False, "窗口句柄已被其他进程复用"
        if require_foreground:
            foreground = int(user32.GetForegroundWindow() or 0)
            if not self.is_allowed_window(target, foreground):
                return False, "目标窗口失去焦点"
        return True, ""

    def validate_capture_geometry(self, target: TargetWindow, captured: Rect) -> tuple[bool, str]:
        return self.validate_capture_geometry_for(target, captured, target.hwnd)

    def validate_capture_geometry_for(
        self, target: TargetWindow, captured: Rect, capture_hwnd: int = 0
    ) -> tuple[bool, str]:
        hwnd = capture_hwnd or target.hwnd
        if not self.is_allowed_window(target, hwnd):
            return False, "截图窗口已经超出授权范围"
        try:
            current = _client_rect(hwnd)
        except OSError:
            return False, "无法读取目标窗口位置"
        if current != captured:
            return False, "截图后目标窗口发生了移动或缩放"
        return True, ""

    def activate(self, target: TargetWindow) -> bool:
        if user32.IsIconic(target.hwnd):
            user32.ShowWindow(target.hwnd, SW_RESTORE)
        self.refresh_owned_windows(target)
        activation_target = target.hwnd
        for choice in self.enumerate_windows():
            if choice.hwnd in target.allowed_owned_hwnds and choice.hwnd != target.hwnd:
                activation_target = choice.hwnd
                break
        return bool(user32.SetForegroundWindow(activation_target))

    def capture_target(self, target: TargetWindow) -> tuple[int, Rect]:
        self.refresh_owned_windows(target)
        foreground = int(user32.GetForegroundWindow() or 0)
        hwnd = foreground if self.is_allowed_window(target, foreground) else target.hwnd
        return hwnd, _client_rect(hwnd)

    @staticmethod
    def foreground_hwnd() -> int:
        return int(user32.GetForegroundWindow() or 0)


def virtual_screen_rect() -> Rect:
    left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    return Rect(left, top, left + width, top + height)


def exclude_window_from_capture(hwnd: int) -> bool:
    try:
        return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


def emergency_hotkey_pressed() -> bool:
    vk_control, vk_shift, vk_f12 = 0x11, 0x10, 0x7B
    return all(user32.GetAsyncKeyState(key) & 0x8000 for key in (vk_control, vk_shift, vk_f12))
