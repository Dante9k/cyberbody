# -*- mode: python ; coding: utf-8 -*-

hiddenimports = [
    "keyring.backends.Windows",
    "win32ctypes.core.ctypes",
    "win32ctypes.core.ctypes._common",
    "win32ctypes.core.ctypes._authentication",
    "win32ctypes.core.ctypes._time",
    "win32ctypes.core.ctypes._system_information",
    "win32ctypes.core.ctypes._resource",
    "win32ctypes.core.ctypes._dll",
]

a = Analysis(
    ["cyberbody_entry.py"],
    pathex=["src"],
    binaries=[],
    datas=[("src/cyberbody/assets/cyberbody-icon.png", "cyberbody/assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=1,
)

# Some development shells put Poppler on PATH. Its ICU DLLs are ABI-incompatible
# with Qt and must not shadow the Windows 10/11 system ICU used by PySide6.
a.binaries = [
    entry
    for entry in a.binaries
    if not (
        entry[0].casefold() in {"icuuc.dll", "icudt78.dll"}
        and "poppler" in str(entry[1]).casefold()
    )
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cyberbody",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    icon=["src/cyberbody/assets/cyberbody-icon.ico"],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="cyberbody",
)
