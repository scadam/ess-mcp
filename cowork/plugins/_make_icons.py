"""Generate color (192x192 RGBA) and outline (32x32 transparent + white) icons
for each Cowork plugin. Idempotent — overwrites in place.
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent

# (folder, hex bg, glyph, brand letter fallback)
PLUGINS = [
    ("servicenow-it-operations", "#62D84E", "lightning", "S"),
    ("workday-people-leader", "#F38B00", "people", "W"),
    ("salesforce-sales-intelligence", "#00A1E0", "cloud", "S"),
    ("coupa-procurement-intelligence", "#6E2DDB", "bag", "C"),
    ("jira-delivery-intelligence", "#0052CC", "stack", "J"),
]

def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("seguisb.ttf", "seguibl.ttf", "segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()

def _draw_glyph(draw: ImageDraw.ImageDraw, glyph: str, size: int, color):
    cx = cy = size // 2
    if glyph == "lightning":
        # bold lightning bolt
        s = size * 0.30
        pts = [
            (cx + s * 0.20, cy - s * 1.40),
            (cx - s * 0.95, cy + s * 0.10),
            (cx - s * 0.10, cy + s * 0.10),
            (cx - s * 0.40, cy + s * 1.40),
            (cx + s * 1.00, cy - s * 0.10),
            (cx + s * 0.10, cy - s * 0.10),
            (cx + s * 0.55, cy - s * 1.40),
        ]
        draw.polygon(pts, fill=color)
    elif glyph == "people":
        # three-circle people group
        r = size * 0.13
        # back two
        for dx in (-0.30, 0.30):
            draw.ellipse((cx + dx*size - r, cy - size*0.30 - r,
                          cx + dx*size + r, cy - size*0.30 + r), fill=color)
            # body
            draw.rounded_rectangle((cx + dx*size - r*1.4, cy - size*0.10,
                                    cx + dx*size + r*1.4, cy + size*0.30),
                                   radius=int(r*0.8), fill=color)
        # front person bigger
        R = size * 0.16
        draw.ellipse((cx - R, cy - size*0.16 - R, cx + R, cy - size*0.16 + R), fill=color)
        draw.rounded_rectangle((cx - R*1.5, cy + size*0.04,
                                cx + R*1.5, cy + size*0.40),
                               radius=int(R*0.9), fill=color)
    elif glyph == "cloud":
        # rounded cloud silhouette
        s = size
        # main blob
        draw.ellipse((cx - s*0.32, cy - s*0.05, cx + s*0.04, cy + s*0.30), fill=color)
        draw.ellipse((cx - s*0.10, cy - s*0.25, cx + s*0.28, cy + s*0.18), fill=color)
        draw.ellipse((cx + s*0.05, cy - s*0.05, cx + s*0.36, cy + s*0.28), fill=color)
        draw.rectangle((cx - s*0.30, cy + s*0.05, cx + s*0.34, cy + s*0.30), fill=color)
    elif glyph == "bag":
        # shopping bag
        s = size
        # body
        draw.rounded_rectangle((cx - s*0.28, cy - s*0.12,
                                cx + s*0.28, cy + s*0.34),
                               radius=int(s*0.06), fill=color)
        # handles (arcs) - draw as outline arcs in bg color via stroke trick: use thicker ellipse
        # simulate handles by drawing two ellipses then erasing inside
        draw.arc((cx - s*0.20, cy - s*0.32, cx - s*0.02, cy - s*0.06),
                 start=180, end=360, fill=color, width=int(s*0.04))
        draw.arc((cx + s*0.02, cy - s*0.32, cx + s*0.20, cy - s*0.06),
                 start=180, end=360, fill=color, width=int(s*0.04))
    elif glyph == "stack":
        # three stacked rounded cards (Kanban / backlog feel)
        s = size
        r = int(s * 0.04)
        for i, dy in enumerate((-0.22, -0.02, 0.18)):
            x0 = cx - s * 0.30
            x1 = cx + s * 0.30
            y0 = cy + s * dy
            y1 = y0 + s * 0.14
            draw.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=color)


def make_color(folder: Path, hex_bg: str, glyph: str, letter: str):
    size = 192
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # rounded square background
    d.rounded_rectangle((4, 4, size - 4, size - 4),
                        radius=36, fill=hex_bg)
    _draw_glyph(d, glyph, size, "white")
    im.save(folder / "color.png", "PNG")


def make_outline(folder: Path, glyph: str):
    size = 32
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    _draw_glyph(d, glyph, size, "white")
    im.save(folder / "outline.png", "PNG")


def main():
    for folder_name, hex_bg, glyph, letter in PLUGINS:
        folder = ROOT / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        make_color(folder, hex_bg, glyph, letter)
        make_outline(folder, glyph)
        print(f"Wrote icons for {folder_name}")


if __name__ == "__main__":
    main()
