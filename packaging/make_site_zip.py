"""Package setup.exe into a zip for handing the app over offline.

site\\index.html links to the GitHub Release asset, so this zip is optional: it is
one file you can pass around without a browser (extract, then run setup.exe).

Usage:
    python packaging\\make_site_zip.py [--setup EXE] [--out ZIP]

Run after packaging\\build.bat has produced
packaging\\output\\AI-Office-Workspace-Setup.exe.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGING_DIR.parent

SETUP_NAME = "AI-Office-Workspace-Setup.exe"
ZIP_NAME = "AI-Office-Workspace-Setup.zip"
DEFAULT_SETUP = PACKAGING_DIR / "output" / SETUP_NAME
DEFAULT_OUT = ROOT_DIR / "site" / ZIP_NAME


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def fail(message: str) -> int:
    print(f"[ERROR] {message}", file=sys.stderr)
    return 1


def build_zip(setup_path: Path, out_path: Path) -> int:
    if not setup_path.is_file():
        return fail(
            f"setup.exe was not found: {setup_path}\n"
            "        Build it first with packaging\\build.bat, then run this again."
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        # setup.exe is already compressed; storing it keeps the build fast and
        # the zip about the same size as the executable alone.
        archive.write(setup_path, SETUP_NAME, compress_type=zipfile.ZIP_STORED)

    print(f"      setup : {setup_path} ({human_size(setup_path.stat().st_size)})")
    print(f"      zip   : {out_path} ({human_size(out_path.stat().st_size)})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Package setup.exe into a zip for handing the app over offline."
    )
    parser.add_argument("--setup", type=Path, default=DEFAULT_SETUP, help="the built setup.exe")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="zip to write")
    args = parser.parse_args()

    return build_zip(args.setup.resolve(), args.out.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
