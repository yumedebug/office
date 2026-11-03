# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for the Windows setup wizard (setup.exe).

Always build through ``packaging/build.bat``.  It runs PyInstaller twice:

1. ``packaging/app.spec``  -> ``packaging/output/AIOfficeWorkspace/``  (the app)
2. ``packaging/setup.spec`` -> ``packaging/output/AI-Office-Workspace-Setup.exe``

This spec packs the application folder produced by step 1 into ``payload.zip``
and embeds it in the setup wizard from ``packaging/setup.py``, so setup.exe is
self-contained: it asks for the install folder, creates the shortcuts and
copies the files.  No Inno Setup (or any other tool) is required.
"""

import zipfile
from pathlib import Path

# SPECPATH is injected by PyInstaller; walk up until the project root is found
# so this works whether it points at the spec file or its directory.
ROOT = Path(SPECPATH).resolve()  # noqa: F821
while not (ROOT / "main.py").exists() and ROOT.parent != ROOT:
    ROOT = ROOT.parent

APP_DIR = ROOT / "packaging" / "output" / "AIOfficeWorkspace"
WORK_DIR = ROOT / "packaging" / "work"
PAYLOAD = WORK_DIR / "payload.zip"
ICON = ROOT / "packaging" / "app.ico"

if not (APP_DIR / "AIOfficeWorkspace.exe").exists():
    raise SystemExit(
        f"[setup] The application build was not found: {APP_DIR}\\AIOfficeWorkspace.exe\n"
        "        Run packaging\\build.bat; it builds the app first."
    )

WORK_DIR.mkdir(parents=True, exist_ok=True)
print(f"[setup] packing {APP_DIR} -> {PAYLOAD}")
with zipfile.ZipFile(PAYLOAD, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(APP_DIR.rglob("*")):
        if path.is_file():
            archive.write(path, path.relative_to(APP_DIR).as_posix())
print(f"[setup] payload: {PAYLOAD.stat().st_size / (1024 * 1024):.0f} MB")

datas = [(str(PAYLOAD), ".")]
if ICON.exists():
    # Window icon of the wizard and icon of setup.exe itself.
    datas.append((str(ICON), "."))

a = Analysis(
    [str(ROOT / "packaging" / "setup.py")],
    pathex=[str(ROOT / "packaging")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The wizard only needs tkinter and the standard library; never pull the
    # application's Qt stack into setup.exe.
    excludes=[
        "PySide6",
        "PyQt5",
        "PyQt6",
        "numpy",
        "PIL",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AI-Office-Workspace-Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    **( {"icon": str(ICON)} if ICON.exists() else {} ),
)
