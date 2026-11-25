"""Generate Memo's logo assets from one 16x16 pixel grid.

The mark: a museum whose columns form an "M" under a gold pediment, with a lime spark (a memory)
glowing in the doorway. Night-ward palette from web/src/styles/tokens.css.
Outputs to web/public/brand/: memo-mark.svg, memo-logo.svg, favicon.svg, favicon.ico, favicon-16/32.png,
apple-touch-icon.png, icon-192/512.png, memo-og-1200x630.png.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(r"D:/Memo/web/public/brand")
OUT.mkdir(parents=True, exist_ok=True)

GRID = [
    "................",
    ".......GG.......",
    ".....GGggGG.....",
    "...GGGggggGGG...",
    ".GGGGGGGGGGGGGG.",
    ".CCCCCCCCCCCCCC.",
    "................",
    "..CCC......CCC..",
    "..CCCC....CCCC..",
    "..CC.CC..CC.CC..",
    "..CC..CCCC..CC..",
    "..CC...LL...CC..",
    "..CC..LLLL..CC..",
    "..CC...LL...CC..",
    ".CCCCCCCCCCCCCC.",
    "GGGGGGGGGGGGGGGG",
]
PAL = {
    "N": "#0b1f4b",   # navy ground
    "G": "#d9a520",   # gold pediment / step
    "g": "#f0c24a",   # pediment highlight
    "C": "#f3f1e2",   # cream marble
    "L": "#a8e27c",   # lime memory spark
}
NAVY = PAL["N"]


def rects(px: float, ox: float = 0, oy: float = 0) -> str:
    out = []
    for y, row in enumerate(GRID):
        x = 0
        while x < 16:
            ch = row[x]
            if ch == ".":
                x += 1
                continue
            run = 1
            while x + run < 16 and row[x + run] == ch:
                run += 1
            out.append(f'<rect x="{ox + x * px:g}" y="{oy + y * px:g}" width="{run * px:g}" height="{px:g}" fill="{PAL[ch]}"/>')
            x += run
    return "".join(out)


def svg_mark(with_ground: bool) -> str:
    ground = f'<rect width="18" height="18" fill="{NAVY}"/>' if with_ground else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18" shape-rendering="crispEdges">'
            f'<title>Memo</title>{ground}{rects(1, 1, 1)}</svg>')


(OUT / "memo-mark.svg").write_text(svg_mark(False), encoding="utf-8")
(OUT / "favicon.svg").write_text(svg_mark(True), encoding="utf-8")

# Horizontal lockup: mark + wordmark (Jersey 10 is loaded by the site; generic fallback elsewhere).
logo = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 22" shape-rendering="crispEdges">'
        f'<title>Memo</title>{rects(1.25, 1, 1)}'
        f'<text x="26" y="18" font-family="\'Jersey 10\', \'Press Start 2P\', monospace" font-size="21" '
        f'letter-spacing="0.6" fill="#f3f1e2">Memo</text></svg>')
(OUT / "memo-logo.svg").write_text(logo, encoding="utf-8")


def raster(size: int, pad_cells: int = 1) -> Image.Image:
    cells = 16 + 2 * pad_cells
    base = Image.new("RGB", (cells, cells), NAVY)
    d = ImageDraw.Draw(base)
    for y, row in enumerate(GRID):
        for x, ch in enumerate(row):
            if ch != ".":
                d.point((x + pad_cells, y + pad_cells), fill=PAL[ch])
    return base.resize((size, size), Image.NEAREST)


for s in (16, 32):
    raster(s, 0 if s == 16 else 1).save(OUT / f"favicon-{s}.png")
raster(180, 1).save(OUT / "apple-touch-icon.png")
raster(192, 1).save(OUT / "icon-192.png")
raster(512, 1).save(OUT / "icon-512.png")
raster(256, 1).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

# Social preview card.
og = Image.new("RGB", (1200, 630), NAVY)
mark = raster(360, 1)
og.paste(mark, (90, 135))
d = ImageDraw.Draw(og)
font_path = next((p for p in ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf") if Path(p).exists()), None)
big = ImageFont.truetype(font_path, 150) if font_path else ImageFont.load_default()
small = ImageFont.truetype(font_path.replace("b.ttf", ".ttf") if font_path else "", 38) if font_path else ImageFont.load_default()
d.text((520, 175), "Memo", font=big, fill=PAL["C"])
d.text((524, 365), "Your family's memories,", font=small, fill="#a7b6d6")
d.text((524, 415), "a museum you can walk through.", font=small, fill="#a7b6d6")
d.rectangle((524, 490, 760, 498), fill=PAL["L"])
og.save(OUT / "memo-og-1200x630.png")
print(sorted(p.name for p in OUT.iterdir()))
