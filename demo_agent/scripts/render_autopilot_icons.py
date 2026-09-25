"""Render original Group Functions Autopilot package artwork; no tenant calls.

Pillow is a build-only dependency in requirements-branding.txt. The outline PNG
is white with alpha on a transparent background, never a scaled color tile.
Only PNG artwork is generated; manifests and CLI credential files are not read.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ACCENT = (177, 31, 75)
SUPERSAMPLING = 6


def mark_mask(size: int) -> Image.Image:
    scale = size * SUPERSAMPLING / 192
    mask = Image.new("L", (size * SUPERSAMPLING, size * SUPERSAMPLING), 0)
    draw = ImageDraw.Draw(mask)

    def xy(values: tuple[float, ...]) -> tuple[float, ...]:
        return tuple(v * scale for v in values)

    # Match the SVG compass arc with connected nodes for people/functions.
    draw.arc(xy((28, 28, 164, 164)), 135, 405, fill=255, width=max(1, round(7 * scale)))
    for x, y in ((96 + 68 * math.cos(math.radians(135)), 96 + 68 * math.sin(math.radians(135))),
                 (96 + 68 * math.cos(math.radians(45)), 96 + 68 * math.sin(math.radians(45))), (96, 28)):
        draw.ellipse(xy((x - 7, y - 7, x + 7, y + 7)), fill=255)
    points = [(round(x * scale), round(y * scale)) for x, y in ((96, 56), (130, 134), (96, 116), (62, 134))]
    draw.polygon(points, fill=255)
    draw.line(points + [points[0]], fill=255, width=max(1, round(3 * scale)), joint="curve")
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def render(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    color = Image.new("RGB", (192, 192), ACCENT)
    color.paste((255, 255, 255), mask=mark_mask(192))
    color.save(directory / "color.png", optimize=True)
    outline = Image.new("RGBA", (32, 32), (255, 255, 255, 0))
    outline.putalpha(mark_mask(32))
    outline.save(directory / "outline.png", optimize=True)
    verify(directory)


def verify(directory: Path) -> None:
    with Image.open(directory / "color.png") as color:
        if color.format != "PNG" or color.size != (192, 192) or color.mode != "RGB":
            raise ValueError("The color icon must be an opaque 192px RGB PNG.")
    with Image.open(directory / "outline.png") as outline:
        if outline.format != "PNG" or outline.size != (32, 32) or outline.mode != "RGBA":
            raise ValueError("The outline icon must be a transparent 32px RGBA PNG.")
        pixels = [outline.getpixel((x, y)) for y in range(32) for x in range(32)]
        if any((r, g, b) != (255, 255, 255) for r, g, b, a in pixels if a):
            raise ValueError("The outline icon may contain only white visible pixels.")
        alpha = outline.getchannel("A")
        if alpha.getextrema() != (0, 255):
            raise ValueError("The outline icon needs both visible and transparent pixels.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a365-manifest-dir", type=Path)
    args = parser.parse_args()
    destinations = [ROOT / "appPackage", ROOT / "manifest"]
    if args.a365_manifest_dir:
        # A staging directory must already contain the CLI manifest, never
        # implicitly create an arbitrary project or credential directory.
        if not (args.a365_manifest_dir / "manifest.json").is_file():
            parser.error("The A365 staging directory must already contain manifest.json.")
        destinations.append(args.a365_manifest_dir.resolve())
    for path in destinations:
        render(path)
        print(f"Validated icons: {path}")


if __name__ == "__main__":
    main()