# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for AI Office Workspace.

Always build through ``packaging/build.bat``: it passes ``--distpath`` and
``--workpath`` so PyInstaller never writes into the repository's own ``dist/``
folder, which holds the compiled frontend.

The result is a one-folder build (``packaging/output/AIOfficeWorkspace``).
Qt WebEngine's helper process, ``resources`` and ``qtwebengine_locales`` are
added by PyInstaller's bundled PySide6 hooks.
"""

from pathlib import Path

# SPECPATH is injected by PyInstaller; walk up until the project root is found
# so this works whether it points at the spec file or its directory.
ROOT = Path(SPECPATH).resolve()  # noqa: F821
while not (ROOT / "main.py").exists() and ROOT.parent != ROOT:
    ROOT = ROOT.parent

ICON = ROOT / "packaging" / "app.ico"

datas = [
    # The compiled React app: main.py loads dist/index.html from here.
    (str(ROOT / "dist"), "dist"),
    # Read-only template; the first launch copies it to the user data folder.
    (str(ROOT / "config.json"), "."),
]

if ICON.exists():
    # Shipped so the window / taskbar icon can be set at runtime.
    datas.append((str(ICON), "."))

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AIOfficeWorkspace",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    # Embed the icon into the .exe (also used by shortcuts and the uninstaller).
    **({"icon": str(ICON)} if ICON.exists() else {}),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AIOfficeWorkspace",
)
