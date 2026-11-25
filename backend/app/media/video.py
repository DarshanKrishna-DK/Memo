"""Videos from Telegram: probe, transcode to a web-friendly MP4 (H.264 + AAC, faststart, longest side <= 1280 px,
first 2 minutes) and grab a poster JPG. Pure ffmpeg/ffprobe; callers run these in a thread.

One transcode at a time per process (`LOCK`): the worker runs several jobs concurrently and ffmpeg is heavy."""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

MAX_SIDE = 1280
MAX_SECONDS = 120.0
LOCK = asyncio.Lock()
EXT_BY_MIME = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm", "video/x-matroska": ".mkv",
               "video/3gpp": ".3gp", "video/mpeg": ".mpg", "video/x-msvideo": ".avi"}


class VideoError(RuntimeError):
    pass


def ext_for(mime: str | None) -> str:
    return EXT_BY_MIME.get((mime or "").lower(), ".mp4")


def probe(path: Path) -> dict:
    """{duration_s, width, height, has_audio, creation_time (aware datetime | None)}. Raises VideoError."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        raise VideoError("ffprobe could not read the video: " + r.stderr.decode("utf-8", "replace")[-300:])
    info = json.loads(r.stdout or b"{}")
    streams = info.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise VideoError("no video stream")
    fmt = info.get("format") or {}
    dur = fmt.get("duration") or v.get("duration")
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    rot = 0
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    if abs(rot) % 180 == 90:
        w, h = h, w
    created = None
    raw = (fmt.get("tags") or {}).get("creation_time") or (v.get("tags") or {}).get("creation_time")
    if raw:
        try:
            created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if not (1990 <= created.year and created <= datetime.now(timezone.utc)):
                created = None                       # 1904/1970 epochs and future stamps are not real capture times
        except ValueError:
            created = None
    return {"duration_s": float(dur) if dur else None, "width": w or None, "height": h or None,
            "has_audio": any(s.get("codec_type") == "audio" for s in streams), "creation_time": created}


def transcode(src: Path, dst: Path, max_side: int = MAX_SIDE, max_s: float = MAX_SECONDS) -> dict:
    """Web MP4 (H.264 high / yuv420p + AAC 128k stereo, +faststart). Silent sources get a silent track so every
    item plays the same way in the browser. Returns probe() of the result."""
    has_audio = probe(src)["has_audio"]
    scale = (f"scale=w='min({max_side},iw)':h='min({max_side},ih)':force_original_aspect_ratio=decrease:"
             f"force_divisible_by=2,setsar=1,format=yuv420p")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(src)]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-t", f"{max_s:.2f}", "-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0",
            "-vf", scale, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-profile:v", "high",
            "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100",
            "-movflags", "+faststart", "-threads", "2", *([] if has_audio else ["-shortest"]), str(dst)]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size < 1000:
        raise VideoError("ffmpeg transcode failed: " + r.stderr.decode("utf-8", "replace")[-800:])
    return probe(dst)


def poster(src: Path, dst: Path, duration_s: float | None, max_side: int = MAX_SIDE) -> None:
    """One JPG frame a third of the way in (max 1 s), so it is rarely a black first frame."""
    at = min(1.0, (duration_s or 0) / 3)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{at:.2f}", "-i", str(src),
           "-frames:v", "1", "-vf",
           f"scale=w='min({max_side},iw)':h='min({max_side},ih)':force_original_aspect_ratio=decrease",
           "-q:v", "3", str(dst)]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0 or not dst.exists():
        raise VideoError("ffmpeg poster failed: " + r.stderr.decode("utf-8", "replace")[-400:])
