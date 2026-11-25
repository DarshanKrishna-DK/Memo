"""Blurry photo detection. Variance of the Laplacian on a 512px grayscale (lower = blurrier), plus a
FFT high-frequency energy ratio as a second signal. Threshold: env BLUR_THRESHOLD (default 100).

Same metric as core-api's app/media/images.py `blur_score` so scores are comparable across both.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Union

import numpy as np
from PIL import Image, ImageOps

from .. import config, db

log = logging.getLogger("memo.blur")
SIZE = 512


def threshold() -> float:
    try:
        return float(config.env("BLUR_THRESHOLD", "100"))
    except ValueError:
        return 100.0


def _gray(src: Union[str, Path, bytes, Image.Image]) -> np.ndarray:
    if isinstance(src, Image.Image):
        img = src
    elif isinstance(src, (bytes, bytearray)):
        img = Image.open(io.BytesIO(src))
    else:
        img = Image.open(src)
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")
    img.thumbnail((SIZE, SIZE), Image.LANCZOS)
    return np.asarray(img, dtype=np.float64)


def _laplacian_var(g: np.ndarray) -> float:
    if g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    lap = (-4.0 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def _hf_ratio(g: np.ndarray) -> float:
    """Share of spectral energy outside the central (low-frequency) quarter of the spectrum."""
    f = np.fft.fftshift(np.fft.fft2(g - g.mean()))
    p = np.abs(f) ** 2
    total = p.sum()
    if total <= 0:
        return 0.0
    h, w = p.shape
    ch, cw = h // 2, w // 2
    rh, rw = max(1, h // 8), max(1, w // 8)
    low = p[ch - rh:ch + rh, cw - rw:cw + rw].sum()
    return float((total - low) / total)


def analyze(src: Union[str, Path, bytes, Image.Image]) -> dict[str, float]:
    g = _gray(src)
    return {"score": _laplacian_var(g), "hf_ratio": _hf_ratio(g)}


def score_image(src: Union[str, Path, bytes, Image.Image]) -> float:
    """Variance of Laplacian (512px grayscale). Lower = blurrier."""
    return _laplacian_var(_gray(src))


def is_blurry(score: float | None, hf_ratio: float | None = None) -> bool:
    """Blurry when the Laplacian score is under the threshold. A borderline score (up to 1.5x the
    threshold) with almost no high-frequency energy is also called blurry."""
    if score is None:
        return False
    t = threshold()
    if score < t:
        return True
    return hf_ratio is not None and score < 1.5 * t and hf_ratio < 0.02


async def rescore_family(family_id: str) -> dict[str, Any]:
    """Re-score every photo in the family's memories and gallery index. Photos the family marked
    'keep' (blur_kept) are scored but never flagged again."""
    from .. import storage

    stats = {"media": 0, "gallery": 0, "flagged": 0, "unreadable": 0}
    rows = await db.fetch(
        "SELECT m.id, m.large_key, m.thumb_key, m.storage_key, m.blur_kept FROM media m "
        "JOIN memories mem ON mem.id = m.memory_id "
        "WHERE mem.family_id=$1::uuid AND m.type='photo' AND mem.status <> 'deleted'", family_id)
    for r in rows:
        key = r["large_key"] or r["storage_key"] or r["thumb_key"]
        try:
            a = analyze(storage.path(key)) if key and storage.exists(key) else None
        except Exception as e:  # noqa: BLE001
            log.warning("blur: cannot read media %s: %s", r["id"], e)
            a = None
        if a is None:
            stats["unreadable"] += 1
            continue
        flag = is_blurry(a["score"], a["hf_ratio"]) and not r["blur_kept"]
        await db.execute("UPDATE media SET blur_score=$2, is_blurry=$3 WHERE id=$1", r["id"], a["score"], flag)
        stats["media"] += 1
        stats["flagged"] += int(flag)
    grows = await db.fetch(
        "SELECT id, path_or_handle, upload_key, source, blur_kept FROM gallery_items WHERE family_id=$1::uuid",
        family_id)
    for r in grows:
        p = gallery_file(r)
        try:
            a = analyze(p) if p and p.exists() else None
        except Exception as e:  # noqa: BLE001
            log.warning("blur: cannot read gallery item %s: %s", r["id"], e)
            a = None
        if a is None:
            stats["unreadable"] += 1
            continue
        flag = is_blurry(a["score"], a["hf_ratio"]) and not r["blur_kept"]
        await db.execute("UPDATE gallery_items SET blur_score=$2, is_blurry=$3 WHERE id=$1", r["id"], a["score"], flag)
        stats["gallery"] += 1
        stats["flagged"] += int(flag)
    return stats


def gallery_file(row) -> Path | None:
    """Local file behind a gallery_items row (folder path, or uploaded object)."""
    from .. import storage
    if row["upload_key"] and storage.exists(row["upload_key"]):
        return storage.path(row["upload_key"])
    if row["source"] == "folder":
        p = Path(row["path_or_handle"])
        if not p.is_absolute():
            p = config.GALLERY_DIR / p
        return p
    return None
