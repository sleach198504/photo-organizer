"""Draws the app icon (a contact sheet: one frame ringed to keep, one slashed to remove)
and writes app.ico, favicon.ico and a PNG into app/web/static/icons.

    python dev/make_icons.py

Drawn at 4x and downsampled so edges are clean at 16 px.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "app" / "web" / "static" / "icons"
SIZE = 1024

BG = (27, 28, 31)
FRAME = (235, 236, 238)
KEEP = (108, 192, 138)
REMOVE = (236, 91, 77)


def draw(size: int = SIZE) -> Image.Image:
    scale = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def box(x, y, w, h):
        return [x * scale, y * scale, (x + w) * scale, (y + h) * scale]

    d.rounded_rectangle(box(0, 0, 64, 64), radius=14 * scale, fill=BG)
    frames = [(9, 9, 0.95), (34, 9, 0.55), (9, 34, 0.55), (34, 34, 0.3)]
    for x, y, alpha in frames:
        color = tuple(int(c * alpha + b * (1 - alpha)) for c, b in zip(FRAME, BG)) + (255,)
        d.rounded_rectangle(box(x, y, 21, 21), radius=4 * scale, fill=color)
    d.rounded_rectangle(box(6.5, 6.5, 26, 26), radius=6.5 * scale, outline=KEEP + (255,), width=max(1, round(3.2 * scale)))
    d.line([(36 * scale, 53 * scale), (53 * scale, 36 * scale)], fill=REMOVE + (255,), width=max(1, round(5.2 * scale)))
    # round caps
    r = 2.6 * scale
    for cx, cy in ((36, 53), (53, 36)):
        d.ellipse([cx * scale - r, cy * scale - r, cx * scale + r, cy * scale + r], fill=REMOVE + (255,))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    master = draw()
    sizes = [16, 24, 32, 48, 64, 128, 256]
    master.save(OUT / "app.ico", sizes=[(s, s) for s in sizes])
    master.save(OUT / "favicon.ico", sizes=[(s, s) for s in (16, 32, 48)])
    master.resize((256, 256), Image.LANCZOS).save(OUT / "app-256.png")
    print("wrote", ", ".join(p.name for p in (OUT / "app.ico", OUT / "favicon.ico", OUT / "app-256.png")))


if __name__ == "__main__":
    main()
