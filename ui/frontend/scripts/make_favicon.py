"""Writes public/favicon.svg and the app icons (icon-192.png, icon-512.png): the same pixel magnifying glass as src/components/Logo.tsx
(keep the two shade() functions in step), light on a dark rounded tile.

    python3 scripts/make_favicon.py   (needs Pillow, e.g. the project's .venv)
"""

import math
from pathlib import Path

GRID, CENTER, RING_OUTER, RING_INNER = 32, 13, 10.4, 7.4
PAD = 4  # tile margin around the 32x32 drawing
INK, TILE = "#f7f8fa", "#0d0f14"


def shade(px: float, py: float) -> float:
    dx, dy = px - CENTER, py - CENTER
    d = math.hypot(dx, dy)
    u, v = (dx + dy) / math.sqrt(2), (dx - dy) / math.sqrt(2)
    if RING_INNER <= d <= RING_OUTER:
        return 1
    if RING_OUTER - 1 <= u <= 14.5 and abs(v) <= 2.3:
        return 1
    if 14.5 < u <= 20.5 and abs(v) <= 3.1:
        return 1
    if u > 20.5 and math.hypot(u - 20.5, v) <= 3:
        return 1
    angle = math.degrees(math.atan2(dy, dx))
    if 4.6 <= d <= 5.8 and -165 <= angle <= -105:
        return 0.55
    if d < RING_INNER:
        return 0.07
    return 0


def main() -> None:
    rects = []
    for y in range(GRID):
        x = 0
        while x < GRID:
            alpha = shade(x + 0.5, y + 0.5)
            width = 1
            while x + width < GRID and shade(x + width + 0.5, y + 0.5) == alpha:
                width += 1
            if alpha:
                opacity = "" if alpha == 1 else f' opacity="{alpha}"'
                rects.append(f'<rect x="{x + PAD}" y="{y + PAD}" width="{width}" height="1" fill="{INK}"{opacity}/>')
            x += width
    size = GRID + 2 * PAD
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
        f'<rect width="{size}" height="{size}" rx="9" fill="{TILE}"/>{"".join(rects)}</svg>\n'
    )
    public = Path(__file__).resolve().parent.parent / "public"
    (public / "favicon.svg").write_text(svg)
    for size in (192, 512):
        write_png(public / f"icon-{size}.png", size)


def write_png(path: Path, size: int) -> None:
    """App icons (window/dock): the same pixels, each drawn as a whole number of pixels."""
    from PIL import Image, ImageDraw

    scale = size * 3 // 4 // GRID  # drawing takes ~3/4 of the tile, in crisp whole pixels
    offset = (size - GRID * scale) // 2
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=TILE)
    ink = tuple(int(INK[i:i + 2], 16) for i in (1, 3, 5))
    for y in range(GRID):
        for x in range(GRID):
            alpha = shade(x + 0.5, y + 0.5)
            if alpha:
                x0, y0 = offset + x * scale, offset + y * scale
                tile = tuple(int(TILE[i:i + 2], 16) for i in (1, 3, 5))
                colour = tuple(round(t + (c - t) * alpha) for c, t in zip(ink, tile))
                draw.rectangle([x0, y0, x0 + scale - 1, y0 + scale - 1], fill=colour)
    img.save(path)


if __name__ == "__main__":
    main()
