#!/usr/bin/env python3
"""Generate ``packaging/app.ico`` for the application and the installer.

Run by ``packaging/build.bat`` (Pillow is listed in
``packaging/requirements-build.txt``).  Replace this script - or simply drop
your own ``app.ico`` next to it and skip this step - if you want custom
artwork.

The drawing is a rounded blue tile with a 3x3 sheet grid, so it still reads as
a spreadsheet at 16 x 16.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - only reached with a broken build env
    print(
        "Pillow が必要です: py -m pip install -r packaging/requirements-build.txt",
        file=sys.stderr,
    )
    raise SystemExit(1)

OUTPUT = Path(__file__).resolve().parent / "app.ico"

#: Rendered once at high resolution, then downscaled into every ICO frame.
BASE_SIZE = 1024
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

GRADIENT_TOP = (110, 155, 245)
GRADIENT_BOTTOM = (56, 90, 166)


def render(size: int) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Vertical gradient background.
    for y in range(size):
        ratio = y / max(size - 1, 1)
        colour = tuple(
            round(top + (bottom - top) * ratio)
            for top, bottom in zip(GRADIENT_TOP, GRADIENT_BOTTOM)
        )
        draw.line([(0, y), (size, y)], fill=colour + (255,))

    # Rounded corners.
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=round(size * 0.22), fill=255
    )
    canvas.putalpha(mask)
    draw = ImageDraw.Draw(canvas)

    # 3 x 3 grid of cells; the top row is a slightly dimmer header.
    margin = round(size * 0.24)
    gap = max(round(size * 0.035), 2)
    span = size - margin * 2
    cell = (span - gap * 2) / 3
    cell_radius = max(round(cell * 0.16), 1)

    for row in range(3):
        for column in range(3):
            x0 = margin + column * (cell + gap)
            y0 = margin + row * (cell + gap)
            # The top row is drawn slightly dimmer: it reads as a header row.
            alpha = 255 if row else 205
            draw.rounded_rectangle(
                [x0, y0, x0 + cell, y0 + cell],
                radius=cell_radius,
                fill=(255, 255, 255, alpha),
            )

    return canvas


def main() -> int:
    image = render(BASE_SIZE)
    image.save(OUTPUT, format="ICO", sizes=[(size, size) for size in ICON_SIZES])
    print(f"generated: {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
