from __future__ import annotations

import ctypes
import getpass
import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_mutex_handle: int | None = None


def server_name() -> str:
    identity = f"{getpass.getuser()}|{Path.home()}".encode("utf-8", errors="ignore")
    suffix = hashlib.sha256(identity).hexdigest()[:12]
    return f"cyberbody-{suffix}"


def acquire_instance_mutex() -> bool:
    global _mutex_handle
    if _mutex_handle:
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    name = f"Local\\{server_name()}-mutex"
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return False
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return False
    _mutex_handle = int(handle)
    return True


def release_instance_mutex() -> None:
    global _mutex_handle
    if not _mutex_handle:
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CloseHandle(ctypes.c_void_p(_mutex_handle))
    _mutex_handle = None


def wait_for_existing(command: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    for _ in range(20):
        response = send_command(command, payload, timeout_ms=250)
        if response is not None:
            return response
        time.sleep(0.1)
    return None


class LocalCommandServer(QObject):
    def __init__(self, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        super().__init__()
        self.handler = handler
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept_connections)

    def listen(self) -> bool:
        name = server_name()
        QLocalServer.removeServer(name)
        return self.server.listen(name)

    def close(self) -> None:
        self.server.close()
        QLocalServer.removeServer(server_name())

    def _accept_connections(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda current=socket: self._read(current))
            socket.disconnected.connect(socket.deleteLater)

    def _read(self, socket: QLocalSocket) -> None:
        raw = bytes(socket.readAll().data()).decode("utf-8", errors="replace").strip()
        try:
            request = json.loads(raw) if raw else {}
            response = self.handler(request)
            payload = {"ok": True, **response}
        except Exception as exc:
            payload = {"ok": False, "error": str(exc)}
        socket.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()


def send_command(
    command: str, payload: dict[str, Any] | None = None, timeout_ms: int = 1500
) -> dict[str, Any] | None:
    socket = QLocalSocket()
    socket.connectToServer(server_name())
    if not socket.waitForConnected(timeout_ms):
        return None
    request = {"command": command, **(payload or {})}
    socket.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
    socket.flush()
    if not socket.waitForReadyRead(timeout_ms):
        return {"ok": False, "error": "cyberbody 没有及时响应"}
    raw = bytes(socket.readAll().data()).decode("utf-8", errors="replace").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": "cyberbody 返回了无效响应"}
