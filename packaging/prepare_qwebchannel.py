#!/usr/bin/env python3
"""Copy Qt's own qwebchannel.js into the places the app loads it from.

A frozen build cannot write next to ``dist/index.html`` (the installation
folder is read-only), so the file has to exist *before* PyInstaller packs
``dist``.  ``packaging/build.bat`` runs this right after ``npm run build``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main  # noqa: E402 - the repository root has to be importable first


def run() -> int:
    # QFile reads the Qt resource below; a Qt application object makes that
    # lookup deterministic across PySide6 builds.
    QCoreApplication(sys.argv[:1])

    script = main.read_qwebchannel_js()
    if not script:
        print("Qt の qwebchannel.js を取得できませんでした。", file=sys.stderr)
        return 1

    targets = (
        main.DIST_DIR / "qtwebchannel.js",
        main.FRONTEND_DIR / "public" / "qtwebchannel.js",
    )
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        changed = not target.exists() or target.read_text(encoding="utf-8") != script
        if changed:
            target.write_text(script, encoding="utf-8")
        print(f"{'updated' if changed else 'unchanged'}: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
