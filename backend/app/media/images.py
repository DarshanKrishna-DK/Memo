"""Photo processing: EXIF read, GPS strip, 1600px + 512px JPEG derivatives, blur score.

process_photo(data, keep_location=False) -> {"original","large","thumb","width","height","taken_at","camera",
    "content_hash","blur_score","is_blurry","mime"}
  - original: the bytes as received, except that location (EXIF GPS IFD, XMP packets with GPS) is removed
    losslessly from JPEG unless keep_location. Pixels are never re-encoded for JPEG.
  - taken_at: EXIF DateTimeOriginal. Aware if the camera wrote OffsetTimeOriginal, otherwise NAIVE local camera
    time (callers localise it to the family timezone).
  - content_hash: sha256 of the bytes as received (used for duplicate detection).
blur_score(img): variance of the Laplacian on a <=512px grayscale copy; is_blurry = score < BLUR_THRESHOLD.
"""
from __future__ import annotations

import hashlib
import io
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image, ImageOps

BLUR_THRESHOLD = 100.0
LARGE_PX = 1600
THUMB_PX = 512
Image.MAX_IMAGE_PIXELS = 160_000_000

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
TAG_DATETIME_ORIGINAL = 36867
TAG_DATETIME_DIGITIZED = 36868
TAG_OFFSET_ORIGINAL = 36881
TAG_DATETIME = 306
TAG_MAKE = 271
TAG_MODEL = 272


def blur_score(img: Image.Image) -> float:
    g = img.convert("L")
    g.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)     # same resampling as media/blur.py, or scores differ ~20% on big photos
    a = np.asarray(g, dtype=np.float32)
    if a.shape[0] < 3 or a.shape[1] < 3:
        return 0.0
    lap = a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:] - 4.0 * a[1:-1, 1:-1]
    return float(lap.var())


def _clean(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bytes):
        v = v.decode("utf-8", "ignore")
    s = str(v).replace("\x00", "").strip()
    return s or None


def read_exif(img: Image.Image) -> tuple[datetime | None, str | None]:
    try:
        ex = img.getexif()
    except Exception:  # noqa: BLE001
        return None, None
    sub = {}
    try:
        sub = ex.get_ifd(EXIF_IFD) or {}
    except Exception:  # noqa: BLE001
        pass
    raw = _clean(sub.get(TAG_DATETIME_ORIGINAL) or sub.get(TAG_DATETIME_DIGITIZED) or ex.get(TAG_DATETIME))
    taken = None
    if raw:
        try:
            taken = datetime.strptime(raw[:19], "%Y:%m:%d %H:%M:%S")
        except ValueError:
            taken = None
        off = _clean(sub.get(TAG_OFFSET_ORIGINAL))
        if taken and off and len(off) >= 6 and off[0] in "+-":
            try:
                sign = 1 if off[0] == "+" else -1
                hh, mm = int(off[1:3]), int(off[4:6])
                taken = taken.replace(tzinfo=timezone(sign * timedelta(hours=hh, minutes=mm)))
            except ValueError:
                pass
    make, model = _clean(ex.get(TAG_MAKE)), _clean(ex.get(TAG_MODEL))
    camera = None
    if make and model:
        camera = model if model.lower().startswith(make.lower().split()[0]) else f"{make} {model}"
    else:
        camera = model or make
    return taken, camera


def _exif_without_gps(body: bytes) -> bytes | None:
    """body = APP1 payload starting with b'Exif\\0\\0'. Returns the payload without the GPS IFD, or None to drop."""
    ex = Image.Exif()
    ex.load(body)
    if GPS_IFD not in ex:
        return body
    del ex[GPS_IFD]
    getattr(ex, "_ifds", {}).pop(GPS_IFD, None)
    out = ex.tobytes()
    return out if len(out) + 2 <= 0xFFFF else None


def _strip_jpeg_location(data: bytes) -> bytes:
    if data[:2] != b"\xff\xd8":
        return data
    out = bytearray(b"\xff\xd8")
    i, n = 2, len(data)
    while i + 1 < n:
        if data[i] != 0xFF:
            out += data[i:]
            break
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0x01,) or 0xD0 <= marker <= 0xD7:
            out += data[i:i + 2]
            i += 2
            continue
        if marker in (0xDA, 0xD9):          # start of scan / end: copy the rest verbatim
            out += data[i:]
            break
        seglen = int.from_bytes(data[i + 2:i + 4], "big")
        seg = data[i:i + 2 + seglen]
        if marker == 0xE1:
            body = seg[4:]
            if body.startswith(b"Exif\x00\x00"):
                try:
                    nb = _exif_without_gps(body)
                except Exception:  # noqa: BLE001 - unparseable EXIF: drop it rather than leak location
                    nb = None
                if nb is None:
                    i += 2 + seglen
                    continue
                seg = b"\xff\xe1" + (len(nb) + 2).to_bytes(2, "big") + nb
            elif body[:29].startswith(b"http://ns.adobe.com/xap/1.0/") and b"GPS" in body:
                i += 2 + seglen                 # XMP packet carrying GPS: drop
                continue
        out += seg
        i += 2 + seglen
    return bytes(out)


def strip_location(data: bytes, fmt: str | None) -> bytes:
    if fmt == "JPEG":
        return _strip_jpeg_location(data)
    img = Image.open(io.BytesIO(data))
    ex = img.getexif()
    if GPS_IFD not in ex:
        return data
    del ex[GPS_IFD]
    getattr(ex, "_ifds", {}).pop(GPS_IFD, None)
    buf = io.BytesIO()
    img.save(buf, fmt or img.format or "PNG", exif=ex.tobytes())
    return buf.getvalue()


def _jpeg(img: Image.Image, px: int, quality: int) -> bytes:
    im = img.copy()
    im.thumbnail((px, px), Image.LANCZOS)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def _open(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def _fmt(img: Image.Image) -> str | None:
    """Pillow reports multi-picture JPEGs (Nikon, Sony, many phones) as 'MPO'. They are plain JPEGs for us:
    stripped losslessly and stored as image/jpeg (as MPO the generic path re-encoded the pixels)."""
    return "JPEG" if img.format == "MPO" else img.format


def inspect(data: bytes) -> dict:
    """Metadata + blur score without producing derivatives (used by the gallery index)."""
    img = _open(data)
    taken, camera = read_exif(img)
    up = ImageOps.exif_transpose(img)
    score = blur_score(up)
    return {"width": up.width, "height": up.height, "taken_at": taken, "camera": camera,
            "content_hash": hashlib.sha256(data).hexdigest(), "blur_score": score,
            "is_blurry": score < BLUR_THRESHOLD, "mime": Image.MIME.get(_fmt(img) or "", "image/jpeg")}


def derivatives(data: bytes) -> dict:
    up = ImageOps.exif_transpose(_open(data))
    return {"large": _jpeg(up, LARGE_PX, 85), "thumb": _jpeg(up, THUMB_PX, 80), "width": up.width,
            "height": up.height}


def process_photo(data: bytes, keep_location: bool = False) -> dict:
    img = _open(data)
    fmt = _fmt(img)
    taken, camera = read_exif(img)
    up = ImageOps.exif_transpose(img)
    score = blur_score(up)
    original = data if keep_location else strip_location(data, fmt)
    return {
        "original": original, "large": _jpeg(up, LARGE_PX, 85), "thumb": _jpeg(up, THUMB_PX, 80),
        "width": up.width, "height": up.height, "taken_at": taken, "camera": camera,
        "content_hash": hashlib.sha256(data).hexdigest(), "blur_score": score, "is_blurry": score < BLUR_THRESHOLD,
        "mime": Image.MIME.get(fmt or "", "image/jpeg"),
    }
