"""Generated video reels. A room (or event) becomes an MP4 (H.264 + AAC) via ffmpeg:
opening card, Ken Burns photos with captions, text-memory cards, kept voice notes mixed in at their slot,
optional Grandma narration under the slideshow, closing card. Night-ward palette, Pillow for all text.
"""
from __future__ import annotations

import asyncio
import calendar
import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .. import bus, config, db, flags, storage

log = logging.getLogger("memo.reels")

NAVY, CREAM, LIME, GOLD = (11, 31, 75), (243, 241, 226), (168, 226, 124), (217, 165, 32)
FPS = 30
XF = 0.8                     # crossfade seconds
PHOTO_S = 5.0
CARD_S = 5.0
SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
FONT_DIR = Path("C:/Windows/Fonts")
LATIN_FONTS = ["segoeui.ttf", "arial.ttf"]
INDIC_FONTS = ["Nirmala.ttc", "Nirmala.ttf", "NirmalaB.ttc"]
# Linux (Docker image: fonts-noto-core + fonts-dejavu). Devanagari and Kannada are separate Noto families.
LINUX_FONT_DIRS = [Path("/usr/share/fonts/truetype/noto"), Path("/usr/share/fonts/opentype/noto"), Path("/usr/share/fonts/truetype/dejavu")]
LINUX_LATIN = ["NotoSans-Regular.ttf", "DejaVuSans.ttf"]
LINUX_LATIN_BOLD = ["NotoSans-Bold.ttf", "DejaVuSans-Bold.ttf"]
LINUX_DEVANAGARI = ["NotoSansDevanagari-Regular.ttf", "NotoSansDevanagari-Regular.otf"]
LINUX_KANNADA = ["NotoSansKannada-Regular.ttf", "NotoSansKannada-Regular.otf"]
INDIC_RE = re.compile("[\u0900-\u097F\u0C80-\u0CFF]")


# ---------------------------------------------------------------- data model
@dataclass
class Slot:
    kind: str                       # 'photo' | 'card'
    dur: float
    image: Path | None = None       # prepared canvas (1.5x output) for the Ken Burns move
    overlay: Path | None = None     # RGBA caption overlay at output size
    audio: Path | None = None       # voice note that starts with this slot
    audio_dur: float = 0.0
    memory_id: str | None = None
    motion: str | None = None       # None = classic alternating centre zoom; else a MOTIONS key


@dataclass
class Plan:
    slots: list[Slot] = field(default_factory=list)
    title: str = ""
    family_name: str = ""
    language: str = "en-IN"
    timed: bool = False             # built for a target length (options.target_s)
    meta: dict = field(default_factory=dict)   # facts for the voiceover script (timed plans)


# Ken Burns moves for timed reels: zoom in/out on the centre or a third, or a slow pan across a zoomed frame.
# Expressions are for ffmpeg zoompan (on = output frame number, F = frames in the slot).
MOTIONS = {
    "in": ("1+0.16*on/{F}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "out": ("1.16-0.16*on/{F}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "pan_r": ("1.18", "(iw-iw/zoom)*on/{F}", "ih/2-(ih/zoom/2)"),
    "pan_l": ("1.18", "(iw-iw/zoom)*(1-on/{F})", "ih/2-(ih/zoom/2)"),
    "in_tl": ("1+0.16*on/{F}", "(iw-iw/zoom)*0.3", "(ih-ih/zoom)*0.3"),
    "in_br": ("1+0.16*on/{F}", "(iw-iw/zoom)*0.7", "(ih-ih/zoom)*0.65"),
}
MOTION_CYCLE = ["in", "pan_r", "out", "in_tl", "pan_l", "in_br"]
TIMED_OPEN_S = 3.4
TIMED_CLOSE_S = 2.8
TIMED_NARRATION_AT = 1.0
from .video import LOCK as REEL_LOCK  # noqa: E402  same lock as video transcodes: one heavy ffmpeg at a time


# ---------------------------------------------------------------- text rendering
def _font(text: str, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = INDIC_FONTS if INDIC_RE.search(text) else ([("segoeuib.ttf" if bold else "segoeui.ttf")] + LATIN_FONTS)
    for n in names:
        p = FONT_DIR / n
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    if not FONT_DIR.exists():       # Linux
        if re.search("[ಀ-೿]", text):
            lnames = LINUX_KANNADA
        elif INDIC_RE.search(text):
            lnames = LINUX_DEVANAGARI
        else:
            lnames = LINUX_LATIN_BOLD if bold else LINUX_LATIN
        for d in LINUX_FONT_DIRS:
            for n in lnames:
                if (d / n).exists():
                    try:
                        return ImageFont.truetype(str(d / n), size)
                    except OSError:
                        continue
    for n in ("DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    raise RuntimeError("no usable TTF font found (looked in C:/Windows/Fonts)")


_HB_FACES: dict = {}


def _shaped_width(text: str, font: ImageFont.FreeTypeFont) -> float:
    """Advance width of `text` in pixels after real HarfBuzz shaping (Pillow here has no raqm, so its own
    textlength ignores conjuncts and matras)."""
    try:
        import uharfbuzz as hb
        key = font.path
        face = _HB_FACES.get(key)
        if face is None:
            face = _HB_FACES[key] = hb.Face(hb.Blob.from_file_path(str(key)))
        hf = hb.Font(face)
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(hf, buf)
        return sum(p.x_advance for p in buf.glyph_positions) * font.size / face.upem
    except Exception:  # noqa: BLE001
        return float(font.getlength(text))


def _tlen(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return _shaped_width(text, font) if INDIC_RE.search(text) else draw.textlength(text, font=font)


def _indic_layer(text: str, font: ImageFont.FreeTypeFont, fill: tuple) -> Image.Image:
    """Pillow here has no libraqm, and ffmpeg's drawtext does not set the script for HarfBuzz, so Devanagari
    and Kannada come out unshaped (matras on the wrong side, visible viramas). libass (the `ass` filter) detects
    the script per run and shapes correctly: render the line white-on-black with it and use that as the alpha
    mask of a solid fill layer."""
    w = int(_shaped_width(text, font)) + int(font.size * 0.6)
    h = int(font.size * 1.9)
    ox, oy = int(font.size * 0.1), int(font.size * 0.25)
    family = font.getname()[0]
    try:
        import uharfbuzz as hb
        face = _HB_FACES.get(font.path) or _HB_FACES.setdefault(font.path, hb.Face(hb.Blob.from_file_path(str(font.path))))
        ext = hb.Font(face).get_font_extents("ltr")
        fs = font.size * (ext.ascender - ext.descender) / face.upem     # libass sizes by ascent+descent, not em
    except Exception:  # noqa: BLE001
        fs = font.size * 1.3
    fdir = Path(str(font.path)).parent.as_posix().replace(":", "\\:")
    safe = text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")
    ass = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 2", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Default,{family},{fs:.2f},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,"
        f"{ox},0,{oy},1", "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,0:00:00.00,0:00:10.00,Default,,0,0,0,,{safe}", ""])
    with tempfile.TemporaryDirectory(prefix="memo_txt_") as td:
        (Path(td) / "t.ass").write_text(ass, encoding="utf-8")
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}",
               "-vf", f"ass=t.ass:fontsdir='{fdir}',format=gray", "-frames:v", "1", "t.png"]
        r = subprocess.run(cmd, capture_output=True, timeout=60, cwd=td)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg ass failed: {r.stderr.decode('utf-8', 'replace')[-800:]}")
        with Image.open(Path(td) / "t.png") as im:
            mask = im.convert("L")
    layer = Image.new("RGBA", mask.size, tuple(fill[:3]) + (0,))
    layer.putalpha(mask.point(lambda v, a=(fill[3] if len(fill) > 3 else 255): v * a // 255))
    return layer


def draw_line(img: Image.Image, xy: tuple[int, int], text: str, font, fill: tuple) -> None:
    if INDIC_RE.search(text):
        layer = _indic_layer(text, font, fill)
        img.paste(layer, (xy[0] - int(font.size * 0.1), xy[1] - int(font.size * 0.25)), layer)
    else:
        ImageDraw.Draw(img).text(xy, text, font=font, fill=fill)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for w in para.split():
            t = f"{cur} {w}".strip()
            if _tlen(draw, t, font) <= max_w or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def _fit_text(draw, text: str, max_w: int, max_h: int, start: int, minimum: int = 28, bold: bool = False):
    size = start
    while True:
        font = _font(text, size, bold)
        lines = _wrap(draw, text, font, max_w)
        lh = int(size * 1.3)
        if len(lines) * lh <= max_h or size <= minimum:
            return font, lines, lh
        size -= 4


def render_card(size: tuple[int, int], heading: str, body: str = "", label: str = "") -> Image.Image:
    W, H = size
    img = Image.new("RGB", size, NAVY)
    d = ImageDraw.Draw(img)
    pad = int(W * 0.09)
    d.rectangle([pad, int(H * 0.16), pad + int(W * 0.07), int(H * 0.16) + 6], fill=LIME)
    y = int(H * 0.20)
    if label:
        f = _font(label, int(min(W, H) * 0.035))
        draw_line(img, (pad, y), label.upper(), f, GOLD)
        y += int(f.size * 2.0)
    avail_h = int(H * 0.78) - y
    head_h = avail_h if not body else int(avail_h * 0.38)
    hf, hl, hlh = _fit_text(d, heading, W - 2 * pad, head_h, int(min(W, H) * 0.095), bold=True)
    for ln in hl:
        draw_line(img, (pad, y), ln, hf, CREAM)
        y += hlh
    if body:
        y += int(hlh * 0.35)
        bf, bl, blh = _fit_text(d, body, W - 2 * pad, int(H * 0.88) - y, int(min(W, H) * 0.048), minimum=24)
        for ln in bl:
            draw_line(img, (pad, y), ln, bf, (220, 218, 200))
            y += blh
    return img


def render_caption(size: tuple[int, int], text: str) -> Image.Image:
    W, H = size
    ov = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    font, lines, lh = _fit_text(d, text, int(W * 0.82), int(H * 0.16), int(min(W, H) * 0.05), minimum=26)
    bar_h = len(lines) * lh + int(lh * 0.8)
    y0 = H - bar_h - int(H * 0.06)
    d.rounded_rectangle([int(W * 0.06), y0, int(W * 0.94), y0 + bar_h], radius=18, fill=(11, 31, 75, 200))
    d.rectangle([int(W * 0.06), y0, int(W * 0.06) + 8, y0 + bar_h], fill=LIME + (255,))
    y = y0 + int(lh * 0.4)
    for ln in lines:
        draw_line(ov, (int(W * 0.09), y), ln, font, CREAM + (255,))
        y += lh
    return ov


def render_tag(size: tuple[int, int], text: str) -> Image.Image:
    """A light caption for timed reels: a small translucent pill in the lower-left corner."""
    W, H = size
    ov = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    font = _font(text, max(22, int(min(W, H) * 0.032)))
    tw = int(_tlen(d, text, font))
    pad_x, pad_y = int(font.size * 0.7), int(font.size * 0.45)
    x0, y1 = int(W * 0.05), H - int(H * 0.06)
    y0 = y1 - int(font.size * 1.35) - 2 * pad_y
    d.rounded_rectangle([x0, y0, x0 + tw + 2 * pad_x + 10, y1], radius=int(font.size * 0.6), fill=(11, 31, 75, 150))
    d.rectangle([x0, y0 + 6, x0 + 5, y1 - 6], fill=LIME + (230,))
    draw_line(ov, (x0 + pad_x + 6, y0 + pad_y), text, font, CREAM + (240,))
    return ov


def prepare_photo(path: Path, size: tuple[int, int], scale: float = 1.5) -> Image.Image:
    """Cover-fit when the aspect is close, otherwise a blurred backdrop with the photo contained."""
    W, H = int(size[0] * scale), int(size[1] * scale)
    src = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    sw, sh = src.size
    if abs((sw / sh) / (W / H) - 1) < 0.18:
        return ImageOps.fit(src, (W, H), Image.LANCZOS)
    bg = ImageOps.fit(src, (W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(14)).resize((W, H))
    bg = Image.blend(bg, Image.new("RGB", (W, H), NAVY), 0.45)
    fg = ImageOps.contain(src, (W, H), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    return bg


# ---------------------------------------------------------------- planning
def month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"


async def load_memories(family_id: str, year: int, month: int, event_id: str | None) -> list[dict]:
    """Same order as the theater showcase: date order, album photos by taken order."""
    rows = await db.fetch(
        "SELECT id, kind, title, text_original, summary, language, event_day, captured_at, "
        "(SELECT nickname FROM members WHERE id=memories.author_id) AS author_name FROM memories "
        "WHERE family_id=$1::uuid AND status='saved' AND event_year=$2 AND event_month=$3 "
        "AND ($4::uuid IS NULL OR event_id=$4::uuid) "
        "ORDER BY event_day NULLS LAST, captured_at, id", family_id, year, month, event_id)
    skip_blurry = bool(await flags.get("auto_skip_blurry", family_id))
    out = []
    for r in rows:
        media = await db.fetch(
            "SELECT id, type, storage_key, large_key, thumb_key, audio_kept, duration_s, transcript, is_blurry, "
            "blur_score "
            "FROM media WHERE memory_id=$1 ORDER BY sort_order, taken_at NULLS LAST, created_at", r["id"])
        photos = [m for m in media if m["type"] == "photo" and (m["large_key"] or m["storage_key"])
                  and not (skip_blurry and m["is_blurry"])]
        voices = [m for m in media if m["type"] == "voice" and m["audio_kept"] and m["storage_key"]]
        out.append({**dict(r), "photos": photos, "voices": voices})
    return out


async def build_plan(family_id: str, year: int, month: int, event_id: str | None,
                     size: tuple[int, int], work: Path, options: dict | None = None) -> Plan:
    fam = await db.fetchrow("SELECT name, language FROM families WHERE id=$1::uuid", family_id)
    if not fam:
        raise RuntimeError("family not found")
    plan = Plan(family_name=fam["name"], language=fam["language"])
    event_name = None
    if event_id:
        ev = await db.fetchrow("SELECT name FROM events WHERE id=$1::uuid AND family_id=$2::uuid", event_id, family_id)
        event_name = ev["name"] if ev else None
    plan.title = f"{month_label(year, month)} \u00b7 {fam['name']}"
    mems = await load_memories(family_id, year, month, event_id)
    opts = options or {}
    if opts.get("target_s"):
        return await _timed_plan(plan, family_id, year, month, event_id, event_name, mems, size, work, opts)

    n = 0

    def save_img(img: Image.Image, suffix: str = ".jpg") -> Path:
        nonlocal n
        n += 1
        p = work / f"img{n:03d}{suffix}"
        if suffix == ".jpg":
            img.save(p, quality=92)
        else:
            img.save(p)
        return p

    content: list[Slot] = []
    for m in mems:
        slots: list[Slot] = []
        caption = (m["title"] or "").strip()
        for ph in m["photos"]:
            key = ph["large_key"] or ph["storage_key"]
            if not storage.exists(key):
                log.warning("reel: missing photo object %s", key)
                continue
            canvas = prepare_photo(storage.path(key), size)
            ov = save_img(render_caption(size, caption), ".png") if caption else None
            slots.append(Slot("photo", PHOTO_S, save_img(canvas), ov, memory_id=str(m["id"])))
        text = (m["text_original"] or m["summary"] or "").strip()
        voice_tr = next((v["transcript"] for v in m["voices"] if v["transcript"]), None)
        if not slots and (text or voice_tr or caption):
            body = text or voice_tr or ""
            body = body if len(body) <= 360 else body[:357].rstrip() + "..."
            head = caption or (body.split(".")[0][:80] if body else "A memory")
            if body == head:
                body = ""
            dur = min(9.0, max(CARD_S, 3.0 + len(body) / 22))
            slots.append(Slot("card", dur, save_img(render_card(size, head, body)), memory_id=str(m["id"])))
        if not slots and m["voices"]:
            slots.append(Slot("card", CARD_S, save_img(render_card(size, "A voice note")), memory_id=str(m["id"])))
        if not slots:
            continue
        for v in m["voices"]:
            if not storage.exists(v["storage_key"]):
                continue
            d = float(v["duration_s"] or probe_duration(storage.path(v["storage_key"])))
            slots[0].audio, slots[0].audio_dur = storage.path(v["storage_key"]), d
            span = sum(s.dur for s in slots) - XF * (len(slots) - 1)
            if d + 0.8 > span:
                slots[-1].dur += d + 0.8 - span          # hold until the voice note finishes
            break
        content.extend(slots)
    if not content:
        raise RuntimeError("this room has nothing to put in a reel (no photos, text or voice notes)")

    opening = Slot("card", CARD_S, save_img(render_card(size, plan.title, event_name or "", "A family memory")))
    closing = Slot("card", CARD_S, save_img(render_card(size, fam["name"], month_label(year, month), "Kept with care")))
    plan.slots = [opening, *content, closing]
    return plan


def _span(slots: list[Slot]) -> float:
    return sum(s.dur for s in slots) - XF * (len(slots) - 1)


async def _timed_plan(plan: Plan, family_id: str, year: int, month: int, event_id: str | None,
                      event_name: str | None, mems: list[dict], size: tuple[int, int], work: Path,
                      opts: dict) -> Plan:
    """A photo montage built to a target length: title card, the sharpest `max_photos` photos (shown in date
    order) with varied Ken Burns moves, crossfades and a light caption, then a short closing card."""
    target = float(opts["target_s"])
    head = (opts.get("title") or "").strip() or event_name or month_label(year, month)
    pool = [(m, ph) for m in mems for ph in m["photos"]
            if storage.exists(ph["large_key"] or ph["storage_key"])]
    if not pool:
        raise RuntimeError("this room has no usable photos for a timed reel")
    chosen = pool
    cap = int(opts.get("max_photos") or 0)
    if cap and len(pool) > cap:
        best = sorted(range(len(pool)), key=lambda i: -(pool[i][1]["blur_score"] or 0.0))[:cap]
        chosen = [pool[i] for i in sorted(best)]            # sharpest N, kept in date order
    n = len(chosen)
    per = (target - TIMED_OPEN_S - TIMED_CLOSE_S + XF * (n + 1)) / n
    per = max(2.2, min(8.0, per))

    def save(img: Image.Image, name: str) -> Path:
        p = work / name
        img.save(p, quality=92) if name.endswith(".jpg") else img.save(p)
        return p

    when = month_label(year, month)
    slots = [Slot("card", TIMED_OPEN_S, save(render_card(size, head, f"{when} · {plan.family_name}",
                                                         "A family memory"), "open.jpg"), motion="in")]
    for i, (m, ph) in enumerate(chosen):
        canvas = prepare_photo(storage.path(ph["large_key"] or ph["storage_key"]), size)
        tag = save(render_tag(size, f"{head} · {when} · {i + 1}/{n}"), f"tag{i:03d}.png")
        slots.append(Slot("photo", per, save(canvas, f"ph{i:03d}.jpg"), tag, memory_id=str(m["id"]),
                          motion=MOTION_CYCLE[i % len(MOTION_CYCLE)]))
    slots.append(Slot("card", TIMED_CLOSE_S, save(render_card(size, plan.family_name, when, "Kept with care"),
                                                  "close.jpg"), motion="out"))
    authors: list[str] = []
    for m, _ in chosen:
        if m.get("author_name") and m["author_name"] not in authors:
            authors.append(m["author_name"])
    plan.slots, plan.timed, plan.title = slots, True, head
    plan.meta = {"title": head, "when": when, "photos_in_room": len(pool), "shown": n, "authors": authors,
                 "set_aside_blurry": await _set_aside(family_id, year, month, event_id)}
    return plan


async def _set_aside(family_id: str, year: int, month: int, event_id: str | None) -> int:
    """Blurry photos of this room/event that were auto-skipped or deleted (cleanup_history) or are flagged."""
    hist = await db.fetchval(
        "SELECT count(*) FROM cleanup_history WHERE family_id=$1::uuid AND year=$2 AND month=$3 "
        "AND ($4::uuid IS NULL OR event_id=$4::uuid)", family_id, year, month, event_id)
    flagged = await db.fetchval(
        "SELECT count(*) FROM media md JOIN memories m ON m.id=md.memory_id WHERE m.family_id=$1::uuid "
        "AND m.status='saved' AND m.event_year=$2 AND m.event_month=$3 AND ($4::uuid IS NULL OR m.event_id=$4::uuid) "
        "AND md.type='photo' AND md.is_blurry", family_id, year, month, event_id)
    return int(hist or 0) + int(flagged or 0)


_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else "-" + _ONES[n % 10])
    return str(n)


def facts_script(meta: dict, language: str) -> str | None:
    """Grandma's voiceover for a timed reel, only from facts in the database (event name, month, photo counts,
    who sent them). English only for now (None otherwise -> the caller uses Grandma's tour instead)."""
    if not language.startswith("en"):
        return None
    names = [a.replace("_", " ").strip() for a in meta.get("authors") or [] if a]
    who = (", ".join(names[:-1]) + " and " + names[-1]) if len(names) > 1 else (names[0] if names else "The family")
    total, shown, aside = meta["photos_in_room"], meta["shown"], meta.get("set_aside_blurry") or 0
    pl = lambda k, one, many: one if k == 1 else many  # noqa: E731
    # Short on purpose: Grandma's aged voice reads ~1.45 words/s, so ~37 words fill a 30 s reel.
    out = [f"Come, sit with me. This is {meta['title']}, {meta['when']}."]
    if shown < total:
        out.append(f"{who} sent {_words(total)} {pl(total, 'photo', 'photos')}; here are the {_words(shown)} clearest.")
    else:
        out.append(f"{who} sent {_words(total)} {pl(total, 'photo', 'photos')}, and here {pl(total, 'it is', 'they all are')}.")
    if aside:
        out.append(f"{_words(aside).capitalize()} blurry {pl(aside, 'one was', 'ones were')} set aside.")
    out.append("I'm so glad these days are kept safe with us.")
    return " ".join(out)


async def fetch_facts_narration(family_id: str, plan: Plan, work: Path) -> tuple[Path, str]:
    """One TTS call in Grandma's voice (app.ai.tts, aged-voice FX included). Returns (mp3 path, script)."""
    text = facts_script(plan.meta, plan.language)
    if not text:
        raise LookupError("no facts script for this language")
    from ..ai import tts  # owned by voice-ai
    res = await tts.synthesize(text, plan.language, None, "mp3", family_id=family_id)
    dest = work / "narration.mp3"
    shutil.copyfile(storage.path(res["storage_key"]), dest)
    return dest, text


def stretch_to(slots: list[Slot], need: float) -> None:
    """Lengthen the photo slots evenly so the reel lasts at least `need` seconds."""
    have = _span(slots)
    photos = [s for s in slots if s.kind == "photo"] or slots
    if need > have:
        add = (need - have) / len(photos)
        for s in photos:
            s.dur += add


# ---------------------------------------------------------------- ffmpeg
def _run(cmd: list[str], timeout: int = 1800) -> None:
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({r.returncode}): {r.stderr.decode('utf-8', 'replace')[-1800:]}")


def probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, timeout=60)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001
        return 0.0


def starts(slots: list[Slot]) -> list[float]:
    t, out = 0.0, []
    for s in slots:
        out.append(t)
        t += s.dur - XF
    return out


def encode(slots: list[Slot], size: tuple[int, int], out: Path, narration: Path | None = None,
           narration_at: float | None = None) -> float:
    """One ffmpeg run: Ken Burns per slot, xfade chain, audio mix (voice notes at their slot + narration).
    narration_at: seconds into the reel where narration starts (default: just after the opening card)."""
    W, H = size
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    chains: list[str] = []
    idx = 0
    for i, s in enumerate(slots):
        frames = max(2, int(round(s.dur * FPS)))
        cmd += ["-i", str(s.image)]
        if s.motion in MOTIONS:
            z, x, y = (e.replace("{F}", str(frames)) for e in MOTIONS[s.motion])
        else:
            z = f"1+0.10*on/{frames}" if i % 2 == 0 else f"1.10-0.10*on/{frames}"
            x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        c = (f"[{idx}:v]zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
             f"setsar=1,format=yuv420p")
        idx += 1
        if s.overlay:
            cmd += ["-i", str(s.overlay)]
            c += f"[b{i}];[{idx}:v]format=rgba[o{i}];[b{i}][o{i}]overlay=0:0:format=auto,format=yuv420p"
            idx += 1
        chains.append(f"{c},settb=AVTB[v{i}]")
    cur, acc = "v0", slots[0].dur
    for i in range(1, len(slots)):
        nxt = f"x{i}"
        chains.append(f"[{cur}][v{i}]xfade=transition=fade:duration={XF}:offset={acc - XF:.3f}[{nxt}]")
        acc += slots[i].dur - XF
        cur = nxt
    total = acc
    st = starts(slots)
    a_labels: list[str] = []
    for i, s in enumerate(slots):
        if s.audio:
            cmd += ["-i", str(s.audio)]
            ms = int(st[i] * 1000)
            chains.append(f"[{idx}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{i}]")
            a_labels.append(f"[a{i}]")
            idx += 1
    if narration:
        cmd += ["-i", str(narration)]
        ms = int(((CARD_S - XF + 0.5) if narration_at is None else narration_at) * 1000)
        chains.append(f"[{idx}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={ms}|{ms},volume=0.95[an]")
        a_labels.append("[an]")
        idx += 1
    if not a_labels:
        chains.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{total:.3f}[aout]")
    elif len(a_labels) == 1:
        chains.append(f"{a_labels[0]}apad,atrim=0:{total:.3f}[aout]")
    else:
        chains.append(f"{''.join(a_labels)}amix=inputs={len(a_labels)}:normalize=0:duration=longest,"
                      f"apad,atrim=0:{total:.3f}[aout]")
    script = out.with_suffix(".filter.txt")
    script.write_text(";\n".join(chains), encoding="utf-8")
    cmd += ["-/filter_complex", str(script), "-map", f"[{cur}]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-t", f"{total:.3f}", str(out)]
    _run(cmd)
    return total


# ---------------------------------------------------------------- narration
async def fetch_narration(family_id: str, year: int, month: int, event_id: str | None,
                          language: str, work: Path) -> Path:
    """Grandma's tour audio (voice-ai). Raises on any failure; the caller decides how to report it."""
    from ..voice import grandma  # owned by voice-ai
    sp = await grandma.tour(family_id, year, month, event_id, language)
    url = sp.get("audio_url") if isinstance(sp, dict) else None
    if not url:
        raise RuntimeError("Grandma's tour returned no audio")
    dest = work / "narration.mp3"
    u = urlparse(url)
    if u.path.startswith("/media/"):
        key = unquote(u.path[len("/media/"):])
        if storage.exists(key):
            shutil.copyfile(storage.path(key), dest)
            return dest
    import httpx
    full = url if u.scheme else f"{config.PUBLIC_BASE_URL}{url}"
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        r = await c.get(full)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


# ---------------------------------------------------------------- job body
async def render_reel(reel_id: str) -> dict:
    row = await db.fetchrow("SELECT * FROM reels WHERE id=$1::uuid", reel_id)
    if not row:
        raise RuntimeError(f"reel {reel_id} not found")
    fid = str(row["family_id"])
    await db.execute("UPDATE reels SET status='rendering', error=NULL, updated_at=now() WHERE id=$1", row["id"])
    size = SIZES.get(row["aspect"], SIZES["16:9"])
    work = Path(tempfile.mkdtemp(prefix="memo_reel_"))
    note = None
    try:
        if not await flags.get("video_reels", fid):
            raise RuntimeError("video reels are switched off for this family")
        event_id = str(row["event_id"]) if row["event_id"] else None
        opts = dict(row["options"] or {}) if "options" in row.keys() else {}
        plan = await build_plan(fid, row["year"], row["month"], event_id, size, work, opts)
        narration, script = None, None
        nar_at = TIMED_NARRATION_AT if plan.timed else None
        if row["narrated"]:
            try:
                if opts.get("voiceover") == "facts" and plan.timed and facts_script(plan.meta, plan.language):
                    narration, script = await fetch_facts_narration(fid, plan, work)
                else:
                    narration = await fetch_narration(fid, row["year"], row["month"], event_id, plan.language, work)
                nd = probe_duration(narration)
                if plan.timed:
                    stretch_to(plan.slots, TIMED_NARRATION_AT + nd + 1.2)   # longer photos, never cut her off
                else:
                    need = CARD_S - XF + 0.5 + nd + 1.0
                    have = _span(plan.slots)
                    if need > have:
                        plan.slots[-1].dur += need - have      # hold the closing card until she finishes
            except Exception as e:  # noqa: BLE001
                narration = None
                note = f"narration skipped: {type(e).__name__}: {e}"[:500]
                log.warning("reel %s %s", reel_id, note)
        if script:
            await db.execute("UPDATE reels SET options = options || jsonb_build_object('script', $2::text) "
                             "WHERE id=$1", row["id"], script)
        out = work / "reel.mp4"
        async with REEL_LOCK:                              # heavy ffmpeg: one render at a time per process
            total = await asyncio.to_thread(encode, plan.slots, size, out, narration, nar_at)
        dur = probe_duration(out) or total
        key = storage.new_key(fid, "reels", ".mp4")
        dest = storage.path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, out, dest)
        old = row["storage_key"]
        await db.execute(
            "UPDATE reels SET status='ready', storage_key=$2, duration_s=$3, error=$4, narrated=$5, updated_at=now() "
            "WHERE id=$1", row["id"], key, float(dur), note, narration is not None)
        if old:
            storage.delete(old)
        await bus.publish(fid, {"type": "reel_ready", "reel_id": str(row["id"]), "year": row["year"],
                                "month": row["month"], "url": storage.signed_url(key)})
        return {"reel_id": str(row["id"]), "duration_s": float(dur), "storage_key": key}
    except Exception as e:  # noqa: BLE001
        await db.execute("UPDATE reels SET status='failed', error=$2, updated_at=now() WHERE id=$1",
                         row["id"], f"{type(e).__name__}: {e}"[:1500])
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def send_reel_to_telegram(reel_id: str, chat_id: int) -> None:
    row = await db.fetchrow("SELECT * FROM reels WHERE id=$1::uuid", reel_id)
    if not row or row["status"] != "ready" or not row["storage_key"]:
        raise RuntimeError("that reel is not ready yet")
    from ..telegram import send as tgsend      # owned by capture-telegram
    await tgsend.send_video(chat_id, storage.path(row["storage_key"]), caption=month_label(row["year"], row["month"]))
