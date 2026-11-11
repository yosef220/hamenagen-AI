"""Build icon.ico (from sizes rendered one by one, so small ones stay crisp)
and the white taskbar-button glyphs (16 px + @2x) used by the player.

    python scripts/make-icons.py <rendered-png-folder> <assets-folder>
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ICO_SIZES = [256, 128, 64, 48, 40, 32, 24, 20, 16]


def build_ico(rendered: Path, assets: Path) -> None:
    images = [Image.open(rendered / f"icon-{s}.png").convert("RGBA") for s in ICO_SIZES]
    images[0].save(assets / "icon.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=images[1:])


def glyph(name: str, size: int) -> Image.Image:
    """Media glyphs drawn on a 16-unit grid, scaled to ``size``."""
    k = size / 16
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    white = (255, 255, 255, 255)
    poly = lambda pts: d.polygon([(x * k, y * k) for x, y in pts], fill=white)  # noqa: E731
    rect = lambda x0, y0, x1, y1: d.rectangle([x0 * k, y0 * k, x1 * k - 1, y1 * k - 1], fill=white)  # noqa: E731
    if name == "play":
        poly([(4, 2.5), (13.5, 8), (4, 13.5)])
    elif name == "pause":
        rect(3.5, 2.5, 6.5, 13.5)
        rect(9.5, 2.5, 12.5, 13.5)
    elif name == "next":
        poly([(2.5, 3), (10.5, 8), (2.5, 13)])
        rect(11, 3, 13.5, 13)
    elif name == "previous":
        poly([(13.5, 3), (5.5, 8), (13.5, 13)])
        rect(2.5, 3, 5, 13)
    return im


def build_thumbar(assets: Path) -> None:
    folder = assets / "thumbar"
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("play", "pause", "next", "previous"):
        glyph(name, 16).save(folder / f"{name}.png")
        glyph(name, 32).save(folder / f"{name}@2x.png")


if __name__ == "__main__":
    rendered, assets = Path(sys.argv[1]), Path(sys.argv[2])
    build_ico(rendered, assets)
    build_thumbar(assets)
    print("icon.ico + taskbar glyphs written")
