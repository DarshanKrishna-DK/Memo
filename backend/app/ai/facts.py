"""General festival facts for Grandma ("what is the essence of Diwali?").

Source: the Wikipedia REST page summary (https://{wiki}.wikipedia.org/api/rest_v1/page/summary/{title}) in the
family's language (hi / kn wiki via the English article's language link), falling back to English.
Only the festival's NAME ever leaves the server, and only names from the curated list below (or a festival
already stored on the family's memories) are looked up. Cached per festival + language in `festival_facts`.
Behind the `general_knowledge` flag.

    await festival_summary("Diwali", "hi-IN", family_id) -> {"festival","language","summary","source_url","cached"} | None
    match_festival(text) -> canonical English festival name | None
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import quote

import httpx

from .. import config, db, flags
from ..voice import lang as L

log = logging.getLogger("memo.facts")

# Wikimedia's robot policy rejects (403) user agents without a contact URL. WIKI_USER_AGENT overrides.
_ua = config.env("WIKI_USER_AGENT") or f"MemoMuseum/0.1 ({config.WEB_BASE_URL}; festival facts) httpx/{httpx.__version__}"
UA = {"User-Agent": _ua, "Api-User-Agent": _ua}
CACHE_DAYS = 30

# canonical name -> (English Wikipedia title, spoken aliases in en / hi / kn)
FESTIVALS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Diwali": ("Diwali", ("diwali", "deepavali", "deepawali", "दिवाली", "दीपावली", "ದೀಪಾವಳಿ")),
    "Holi": ("Holi", ("holi", "होली", "ಹೋಳಿ")),
    "Eid al-Fitr": ("Eid al-Fitr", ("eid", "eid ul fitr", "eid al-fitr", "ramzan eid", "ईद", "ಈದ್", "ರಂಜಾನ್")),
    "Eid al-Adha": ("Eid al-Adha", ("bakrid", "eid al-adha", "eid ul adha", "बकरीद", "ಬಕ್ರೀದ್")),
    "Christmas": ("Christmas", ("christmas", "xmas", "क्रिसमस", "ಕ್ರಿಸ್ಮಸ್")),
    "Pongal": ("Thai Pongal", ("pongal", "पोंगल", "ಪೊಂಗಲ್")),
    "Onam": ("Onam", ("onam", "ओणम", "ಓಣಂ")),
    "Ugadi": ("Ugadi", ("ugadi", "yugadi", "उगादी", "ಯುಗಾದಿ", "ಉಗಾದಿ")),
    "Navaratri": ("Navaratri", ("navaratri", "navratri", "नवरात्रि", "ನವರಾತ್ರಿ")),
    "Dussehra": ("Vijayadashami", ("dussehra", "dasara", "dasera", "vijayadashami", "दशहरा", "ದಸರಾ", "ವಿಜಯದಶಮಿ")),
    "Ganesh Chaturthi": ("Ganesh Chaturthi", ("ganesh chaturthi", "ganesha chaturthi", "ganeshotsav", "गणेश चतुर्थी",
                                             "ಗಣೇಶ ಚತುರ್ಥಿ", "ಗಣೇಶ ಹಬ್ಬ")),
    "Raksha Bandhan": ("Raksha Bandhan", ("raksha bandhan", "rakhi", "रक्षाबंधन", "रक्षा बंधन", "राखी", "ರಕ್ಷಾ ಬಂಧನ")),
    "Makar Sankranti": ("Makar Sankranti", ("sankranti", "makar sankranti", "मकर संक्रांति", "ಸಂಕ್ರಾಂತಿ")),
    "Janmashtami": ("Krishna Janmashtami", ("janmashtami", "gokulashtami", "जन्माष्टमी", "ಜನ್ಮಾಷ್ಟಮಿ", "ಗೋಕುಲಾಷ್ಟಮಿ")),
    "Durga Puja": ("Durga Puja", ("durga puja", "दुर्गा पूजा", "ದುರ್ಗಾ ಪೂಜೆ")),
    "Lohri": ("Lohri", ("lohri", "लोहड़ी")),
    "Vaisakhi": ("Vaisakhi", ("baisakhi", "vaisakhi", "बैसाखी")),
    "Karva Chauth": ("Karva Chauth", ("karva chauth", "karwa chauth", "करवा चौथ")),
    "Gudi Padwa": ("Gudi Padwa", ("gudi padwa", "गुड़ी पड़वा")),
    "Vishu": ("Vishu", ("vishu", "ವಿಷು")),
    "Bihu": ("Bihu", ("bihu", "बिहू")),
    "Easter": ("Easter", ("easter", "ईस्टर", "ಈಸ್ಟರ್")),
    "Maha Shivaratri": ("Maha Shivaratri", ("shivaratri", "shivratri", "maha shivaratri", "महाशिवरात्रि", "शिवरात्रि",
                                            "ಶಿವರಾತ್ರಿ")),
    "Varalakshmi Vratam": ("Varalakshmi Vratam", ("varalakshmi", "varamahalakshmi", "ವರಮಹಾಲಕ್ಷ್ಮಿ")),
    "Guru Nanak Jayanti": ("Guru Nanak Gurpurab", ("guru nanak jayanti", "gurpurab", "गुरु नानक जयंती")),
}


def match_festival(text: str) -> Optional[str]:
    t = (text or "").lower()
    for canon, (_title, aliases) in FESTIVALS.items():
        for a in aliases:
            if (re.search(rf"\b{re.escape(a)}\b", t) if a.isascii() else a in t):
                return canon
    return None


def _wiki_of(language: str) -> str:
    return L.SHORT[L.norm(language)]


async def _langlink(c: httpx.AsyncClient, title: str, wiki: str) -> Optional[str]:
    r = await c.get("https://en.wikipedia.org/w/api.php", params={
        "action": "query", "titles": title, "prop": "langlinks", "lllang": wiki, "redirects": 1,
        "format": "json", "formatversion": 2})
    if r.status_code != 200:
        return None
    for p in r.json().get("query", {}).get("pages", []):
        for ll in p.get("langlinks", []) or []:
            if ll.get("title"):
                return ll["title"]
    return None


async def _summary(c: httpx.AsyncClient, wiki: str, title: str) -> Optional[tuple[str, str]]:
    r = await c.get(f"https://{wiki}.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'), safe='')}",
                    follow_redirects=True)
    if r.status_code != 200:
        return None
    j = r.json()
    text = (j.get("extract") or "").strip()
    if not text or j.get("type") == "disambiguation":
        return None
    url = (j.get("content_urls") or {}).get("desktop", {}).get("page") or f"https://{wiki}.wikipedia.org/wiki/{quote(title)}"
    return text, url


async def festival_summary(festival: str, language: str, family_id: Optional[str] = None) -> Optional[dict]:
    if not await flags.get("general_knowledge", family_id):
        return None
    canon = match_festival(festival) or (festival if festival in FESTIVALS else None)
    if not canon:
        return None
    language = L.norm(language)
    row = await db.fetchrow(
        "SELECT summary, source_url, language FROM festival_facts WHERE festival=$1 AND language=$2 "
        f"AND fetched_at > now() - interval '{CACHE_DAYS} days'", canon, language)
    if row:
        return {"festival": canon, "language": row["language"], "summary": row["summary"],
                "source_url": row["source_url"], "cached": True}
    title = FESTIVALS[canon][0]
    wiki = _wiki_of(language)
    got: Optional[tuple[str, str]] = None
    got_lang = language
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=UA) as c:
            if wiki != "en":
                local = await _langlink(c, title, wiki)
                if local:
                    got = await _summary(c, wiki, local)
            if not got:
                got = await _summary(c, "en", title)
                got_lang = "en-IN"
    except httpx.HTTPError as e:
        log.warning("wikipedia lookup failed: %s", type(e).__name__)
        return None
    if not got:
        return None
    summary, url = got
    await db.execute(
        "INSERT INTO festival_facts(festival, language, summary, source_url) VALUES ($1,$2,$3,$4) "
        "ON CONFLICT (festival, language) DO UPDATE SET summary=EXCLUDED.summary, source_url=EXCLUDED.source_url, "
        "fetched_at=now()", canon, language, summary, url)
    return {"festival": canon, "language": got_lang, "summary": summary, "source_url": url, "cached": False}
