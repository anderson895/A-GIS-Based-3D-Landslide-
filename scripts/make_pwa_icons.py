"""Generate PWA icons for the Malico landslide viewer.

Creates a 192x192, 512x512, and a maskable 512x512 PNG with a simple
terrain-themed glyph. Run once; outputs land in ``viewer/icons/``.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "viewer" / "icons"
OUT.mkdir(parents=True, exist_ok=True)

BG_TOP = (15, 32, 51)        # deep slate
BG_BOTTOM = (24, 64, 88)     # teal-slate
RIDGE_BACK = (90, 130, 140)
RIDGE_MID = (140, 170, 150)
RIDGE_FRONT = (210, 175, 95)  # warm hazard accent
SKY_GLOW = (255, 215, 130, 80)


def _gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size), BG_TOP)
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return img


def _ridges(img: Image.Image, inset: int) -> None:
    """Three overlapping mountain silhouettes."""
    w, h = img.size
    d = ImageDraw.Draw(img, "RGBA")
    base = h - inset

    def poly(points, color):
        d.polygon(points, fill=color)

    poly([
        (inset, base),
        (w * 0.18, base - h * 0.28),
        (w * 0.36, base - h * 0.10),
        (w * 0.55, base - h * 0.34),
        (w * 0.78, base - h * 0.12),
        (w - inset, base - h * 0.22),
        (w - inset, base),
    ], RIDGE_BACK)

    poly([
        (inset, base),
        (w * 0.10, base - h * 0.10),
        (w * 0.30, base - h * 0.30),
        (w * 0.50, base - h * 0.14),
        (w * 0.70, base - h * 0.26),
        (w - inset, base - h * 0.08),
        (w - inset, base),
    ], RIDGE_MID)

    poly([
        (inset, base),
        (w * 0.22, base - h * 0.14),
        (w * 0.42, base - h * 0.22),
        (w * 0.60, base - h * 0.10),
        (w * 0.80, base - h * 0.18),
        (w - inset, base - h * 0.04),
        (w - inset, base),
    ], RIDGE_FRONT)


def _rounded_mask(size: int, radius_ratio: float) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    r = int(size * radius_ratio)
    d.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=r, fill=255)
    return mask


def make_icon(size: int, *, maskable: bool = False) -> Image.Image:
    canvas_size = size
    img = _gradient(canvas_size)

    # Maskable icons must keep important content inside a centered safe zone
    # (~80% of the canvas). Add extra padding so the ridges aren't clipped.
    inset = int(size * (0.18 if maskable else 0.08))
    _ridges(img, inset=inset)

    if not maskable:
        # Round the corners for the standard "any" icon.
        rounded = Image.new("RGBA", img.size, (0, 0, 0, 0))
        rounded.paste(img, (0, 0), _rounded_mask(canvas_size, 0.22))
        img = rounded

    return img


def main() -> None:
    outputs = {
        "icon-192.png": make_icon(192),
        "icon-512.png": make_icon(512),
        "icon-maskable-512.png": make_icon(512, maskable=True),
    }
    for name, im in outputs.items():
        path = OUT / name
        im.save(path, format="PNG", optimize=True)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
