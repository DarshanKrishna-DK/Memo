"""The theater's playlist, built from the room's (or one event's) saved memories in date order.

ShowcaseItem: {memory_id, kind: photo|title|voice|video, type (= kind), url, thumb_url, caption, transcript, audio_url,
duration_s} (+ additive: text, photo_id, index_in_memory, count_in_memory; video: poster_url, video_id, width, height)
- video: plays the web MP4 (`url`) with `poster_url`; `duration_s` is the real clip length (max 120 s).
- photo: about 6 s with its caption; an album plays its photos in the order they were taken.
- title: a written memory (or a voice note whose audio was not kept) as a title card.
- voice: a voice note with its transcript (if kept).
"""
from __future__ import annotations

from . import memories

PHOTO_S = 6.0


def _caption(e: dict) -> str:
    return (e.get("title") or e.get("summary") or (e.get("text") or "").split("\n")[0][:140]
            or e.get("festival") or "").strip()


def _card_seconds(text: str) -> float:
    words = len((text or "").split())
    return float(max(5, min(15, round(4 + words / 3))))


async def build_showcase(family_id, year, month, event_id=None) -> list[dict]:
    items: list[dict] = []
    for e in await memories.room_memories(family_id, year, month, event_id):
        cap = _caption(e)
        photos = e["photos"]
        videos = [v for v in e.get("videos", []) if v["ready"]]
        if e["kind"] == "album":
            photos = sorted(photos, key=lambda p: (p["taken_at"] is None, p["taken_at"] or ""))
        if photos or videos:
            n = len(photos) + len(videos)
            for i, p in enumerate(photos):
                items.append({"memory_id": e["id"], "kind": "photo", "type": "photo", "url": p["url"],
                              "thumb_url": p["thumb_url"],
                              "caption": cap, "transcript": None, "audio_url": None, "duration_s": PHOTO_S,
                              "text": e["text"] if i == 0 else None, "photo_id": p["id"],
                              "index_in_memory": i, "count_in_memory": n})
            for j, v in enumerate(videos):
                # Theater media item for a video (docs/BUILD_CONTRACT.md "Theater media items")
                items.append({"memory_id": e["id"], "kind": "video", "type": "video", "url": v["url"],
                              "poster_url": v["poster_url"], "thumb_url": v["poster_url"], "caption": cap,
                              "transcript": None, "audio_url": None,
                              "duration_s": float(v["duration_s"] or PHOTO_S), "video_id": v["id"],
                              "width": v["width"], "height": v["height"],
                              "text": e["text"] if not photos and j == 0 else None,
                              "index_in_memory": len(photos) + j, "count_in_memory": n})
            continue
        if e.get("videos"):                     # video still being prepared: it joins the playlist once ready
            continue
        if e["kind"] == "voice":
            if e["audio_url"]:
                items.append({"memory_id": e["id"], "kind": "voice", "url": None, "thumb_url": None,
                              "caption": cap, "transcript": e["transcript"], "audio_url": e["audio_url"],
                              "duration_s": float(e["duration_s"] or 6.0), "text": None})
            else:
                body = e["transcript"] or e["text"] or ""
                items.append({"memory_id": e["id"], "kind": "title", "url": None, "thumb_url": None,
                              "caption": cap or body[:140], "transcript": e["transcript"], "audio_url": None,
                              "duration_s": _card_seconds(body), "text": body})
            continue
        body = e["text"] or e["summary"] or ""
        items.append({"memory_id": e["id"], "kind": "title", "url": None, "thumb_url": None,
                      "caption": cap or body[:140], "transcript": None, "audio_url": None,
                      "duration_s": _card_seconds(body), "text": body})
    for it in items:
        it.setdefault("type", it["kind"])
    return items
