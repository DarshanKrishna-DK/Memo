"""Turn checked sentences into a Speech (web/src/contract.ts) spoken one sentence at a time.

Speech = {text, audio_url, subtitles[{text,start_s,end_s}], highlights[{memory_id,at_s}], memory_ids,
          sentences[{index, text, audio_url, duration_s, start_s, end_s, memory_ids}], language, start_index}

`sentences[i].audio_url` is one clip per sentence, so the client can stop cleanly between sentences and report
the last finished index (sent back as `resume_from`). `audio_url` is the same sentences joined into one track
(ffmpeg), for clients that just want to press play; it is the first sentence's clip if ffmpeg is unavailable.
Timings are relative to the start of this Speech (sentence start_index).
"""
from __future__ import annotations

import asyncio
from typing import Optional

from ..ai import tts

GAP_S = 0.0   # the clips carry their own trailing silence


async def build(sentences: list[dict], language: str, voice: str = "grandma", family_id: Optional[str] = None,
                start_index: int = 0, audio: bool = True, join: bool = True) -> dict:
    sel = sentences[start_index:]
    sem = asyncio.Semaphore(4)

    async def one(s: dict) -> Optional[dict]:
        if not audio:
            return None
        async with sem:
            return await tts.synthesize(s["text"], language, voice, family_id=family_id)

    clips = await asyncio.gather(*(one(s) for s in sel))
    t = 0.0
    out_sent, subs, highlights, all_ids = [], [], [], []
    for i, (s, clip) in enumerate(zip(sel, clips)):
        # Without audio, estimate reading time (about 15 characters per second) for subtitle pacing only.
        dur = float(clip["duration_s"]) if clip else max(1.2, len(s["text"]) / 15.0)
        start, end = round(t, 3), round(t + dur, 3)
        ids = list(s.get("memory_ids") or [])
        out_sent.append({"index": start_index + i, "text": s["text"], "audio_url": clip["url"] if clip else None,
                         "storage_key": clip["storage_key"] if clip else None, "duration_s": round(dur, 3),
                         "start_s": start, "end_s": end, "memory_ids": ids})
        subs.append({"text": s["text"], "start_s": start, "end_s": end})
        for mid in ids:
            highlights.append({"memory_id": mid, "at_s": start})
            if mid not in all_ids:
                all_ids.append(mid)
        t = end + GAP_S
    audio_url = None
    if clips and clips[0]:
        audio_url = clips[0]["url"]
        if join and len(clips) > 1:
            joined = await tts.concat([c["storage_key"] for c in clips if c])
            if joined:
                audio_url = joined["url"]
    for s in out_sent:
        s.pop("storage_key", None)
    return {
        "text": " ".join(s["text"] for s in sel),
        "audio_url": audio_url,
        "subtitles": subs,
        "highlights": highlights,
        "memory_ids": all_ids,
        "sentences": out_sent,
        "language": language,
        "start_index": start_index,
        "total_sentences": len(sentences),
    }
