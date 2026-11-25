"""How the user is talking: language, script and code-mixing (Hinglish, Kanglish), plus a thin pre-normaliser
that turns Hinglish / Kanglish / Hindi / Kannada date words, month spellings and common typos into the English
that app.core.dates.resolve_when reads. Pure code, no model calls (latency).

    detect(text)            -> {"lang": "en-IN"|"hi-IN"|"kn-IN"|None, "script": "latin"|"deva"|"knda"|None,
                                "mixed": bool, "register": "en"|"hinglish"|"kanglish"|"hi"|"kn"}
    reply_lang(text, session_lang) -> the language a reply should be voiced in (mirrors Hindi / Kannada input)
    to_english_dates(text, route=False) -> "kal ki saari photos" -> "yesterday ki saari photos"
"""
from __future__ import annotations

import difflib
import re
from typing import Optional

from . import lang as L

DEVA = re.compile(r"[ऀ-ॿ]")
KNDA = re.compile(r"[ಀ-೿]")

# Roman-script Hindi / Kannada words that are not English words (or are rare in English). Each hit counts once.
HINGLISH = set("""
mujhe mujhko humko hume humein hamein tujhe tumhe tumko aapko apko mera meri mere tera teri tere hamara hamari
hamare apna apni apne kya kyu kyun kyon kaise kaisa kaisi kab kahan kaha kidhar idhar udhar yahan wahan jab tab
hai hain tha thi the hoga hogi honge ho raha rahi rahe karo karna kar karke karde kardo karo karoge kiya kiye
dikhao dikha dikhado dikhaao chalo chal chalein chaliye chalte lo lelo jao jaana jana jaana hai daal daalo
dalo daldo daal do bana banao banado banaiye banaana banana naya nayi naye wala wali wale waala waali waale
mein me ko ka ki ke se par pe aur ya bhi nahi nahin nai mat haan han haa hanji theek thik achha accha acha arre
arey are bhai bhaiya yaar yar dekho dekh suno sun bata batao bolo bol saari sari saare sare sab sabhi kuch kuchh
kal parso aaj abhi pichle pichhle pichla pichhla agle agla saal mahina mahine hafte hafta din raat subah shaam
diye diya tasveer tasveerein photu wapas fir phir bas bilkul zaroor jaldi thoda thodi bahut zyada kitne kitni
wahi yahi woh vo voh yeh ye ise usse unka uska iska unki uski iski humne maine tumne aapne gaye gayi gaya
hua hui hue liya liye diya dena dedo do de rakho rakh lagao lagado khol kholo jodo jod jodna batao naam
""".split())
KANGLISH = set("""
nanu nange nanna nannu neenu ninge ninna ninnu naavu namma nammanna avru avara ivru avalu avanu adu idu
yenu enu yaake yake yelli elli hege yavaga yaavaga yaava yava yaaru yaru beku beda bedi beda illa ide idya
maadu madu maadi madi maadona madona maadbidu madbidu maadkodu hogu hogi hogona hogbeku hogbidi baa banni
karkondu karkond kar kondu karedukondu karedukondu hogu thorsu torsu torisu thorisu nodu nodi nodona
ella yella ellaa saku saaku sari sariyaagi haudu houdu howdu hu aytu aaytu aitu hosa hale ninne monne
ivattu indu naale mundina kaleda kalada hoda hodha varsha tingalu tingal vaara dina raatri beligge
alli ge ige ige ಗೆ inda jothe jote mele kelage hatra ondu eradu mooru photogalu photo galu chitra
swalpa tumba sakkat bega aamele amele anta antha andre ade ide adre guru maga magane kanda appa amma ajji
""".split())
# Words that are both English and Hinglish/Kanglish fillers; they never count on their own.
_AMBIGUOUS = {"me", "do", "de", "le", "par", "are", "bhi", "ha", "han", "hu", "baa", "kar", "sari", "ge", "ide",
              "ade", "guru", "amma", "appa", "ajji", "bol", "sun", "din", "the", "ho", "pe", "ya", "aur"}

_WORD = re.compile(r"[a-z]+")


def _hits(words: list[str], lex: set[str]) -> int:
    return sum(1 for w in set(words) if w in lex and w not in _AMBIGUOUS)


def detect(text: str) -> dict:
    t = text or ""
    deva, knda = len(DEVA.findall(t)), len(KNDA.findall(t))
    latin = len(re.findall(r"[A-Za-z]", t))
    words = _WORD.findall(t.lower())
    if knda and knda >= deva:
        return {"lang": "kn-IN", "script": "knda", "mixed": latin > 3, "register": "kn"}
    if deva:
        return {"lang": "hi-IN", "script": "deva", "mixed": latin > 3, "register": "hi"}
    if not words:
        return {"lang": None, "script": None, "mixed": False, "register": "en"}
    h, k = _hits(words, HINGLISH), _hits(words, KANGLISH)
    # Short utterances ("kal ki photos") need one strong marker; longer ones need two.
    need = 1 if len(words) <= 4 else 2
    if k >= need and k > h:
        return {"lang": "kn-IN", "script": "latin", "mixed": True, "register": "kanglish"}
    if h >= need and h >= k:
        return {"lang": "hi-IN", "script": "latin", "mixed": True, "register": "hinglish"}
    return {"lang": "en-IN", "script": "latin", "mixed": False, "register": "en"}


def reply_lang(text: str, session_lang: Optional[str]) -> str:
    """Mirror the user: Hindi / Kannada (any script) gets a reply voiced in that language; plain English keeps the
    session language (a Hindi family typing "Take me to March 2025" still hears Hindi)."""
    d = detect(text)
    if d["lang"] in ("hi-IN", "kn-IN"):
        return d["lang"]
    return L.norm(session_lang)


def register_of(text: str, lang: str) -> str:
    """Reply register for templates: 'hinglish' / 'kanglish' when the user wrote Roman Hindi / Kannada in that
    language, else the plain language."""
    d = detect(text)
    if d["register"] == "hinglish" and L.norm(lang) == "hi-IN":
        return "hinglish"
    if d["register"] == "kanglish" and L.norm(lang) == "kn-IN":
        return "kanglish"
    return L.norm(lang)


# ---------------------------------------------------------------- dates (pre-normaliser for core.dates)

_DIGITS = str.maketrans("०१२३४५६७८९೦೧೨೩೪೫೬೭೮೯", "01234567890123456789")

# Month spellings: Hindi / Kannada Roman forms and common typos -> month number.
ROMAN_MONTHS = {
    "janvari": 1, "janwari": 1, "janavari": 1, "janewari": 1, "farvari": 2, "farwari": 2, "pharvari": 2,
    "febravari": 2, "phebravari": 2, "febuary": 2, "feburary": 2, "febrary": 2, "maarch": 3, "marchi": 3,
    "aprail": 4, "aprel": 4, "epril": 4, "mai": 5, "mei": 5, "joon": 6, "jun": 6, "julai": 7, "julay": 7,
    "agast": 8, "agasta": 8, "agastu": 8, "sitambar": 9, "sitamber": 9, "septembar": 9, "septambar": 9,
    "aktubar": 10, "aktoobar": 10, "aktobar": 10, "octobar": 10, "navambar": 11, "navamber": 11, "navembar": 11,
    "novembar": 11, "novmber": 11, "nevember": 11, "disambar": 12, "disamber": 12, "disembar": 12, "decmber": 12,
    "desember": 12, "dicember": 12,
}
# (pattern, english). Order matters: longer phrases first.
RELATIVE = [
    # Hindi, Devanagari
    (r"परसों", " day before yesterday "), (r"पिछले\s*साल|पिछला\s*साल|पिछली\s*साल|गए\s*साल|गये\s*साल", " last year "),
    (r"पिछले\s*महीने|पिछला\s*महीना", " last month "), (r"पिछले\s*हफ़्ते|पिछले\s*हफ्ते|पिछला\s*हफ़्ता", " last week "),
    (r"इस\s*साल", " this year "), (r"इस\s*महीने", " this month "), (r"इस\s*हफ़्ते|इस\s*हफ्ते", " this week "),
    (r"अगले\s*साल", " next year "), (r"अगले\s*महीने", " next month "), (r"(?<![ऀ-ॿ])कल(?![ऀ-ॿ])", " yesterday "),
    (r"(?<![ऀ-ॿ])आज(?![ऀ-ॿ])", " today "),
    # Kannada, Kannada script
    (r"ಮೊನ್ನೆ", " day before yesterday "), (r"ನಿನ್ನೆ", " yesterday "), (r"ಇವತ್ತು|ಇಂದು", " today "),
    (r"ಕಳೆದ\s*ವರ್ಷ|ಹೋದ\s*ವರ್ಷ|ಹೋದ\s*ವರುಷ", " last year "), (r"ಕಳೆದ\s*ತಿಂಗಳು|ಹೋದ\s*ತಿಂಗಳು|ಕಳೆದ\s*ತಿಂಗಳ", " last month "),
    (r"ಕಳೆದ\s*ವಾರ|ಹೋದ\s*ವಾರ", " last week "), (r"ಈ\s*ವರ್ಷ", " this year "), (r"ಈ\s*ತಿಂಗಳು|ಈ\s*ತಿಂಗಳ", " this month "),
    (r"ಮುಂದಿನ\s*ವರ್ಷ", " next year "), (r"ಮುಂದಿನ\s*ತಿಂಗಳು", " next month "),
    # Hinglish (Roman)
    (r"\bparso[n]?\b|\bparson\b", " day before yesterday "),
    (r"\b(pichle|pichhle|pichla|pichhla|pichli|pichhli|picle|pichele|gaye|gae|gya|last)\s+(saal|sal|year)(\s+(wala|wali|wale|waala|waali|waale|ka|ki|ke|wala\s+\w+))?\b", " last year "),
    (r"\b(pichle|pichhle|pichla|pichhla|picle|last)\s+(mahine|mahina|month)\b", " last month "),
    (r"\b(pichle|pichhle|pichla|pichhla|last)\s+(hafte|hafta|week)\b", " last week "),
    (r"\b(is|iss|ish)\s+(saal|sal)\b", " this year "), (r"\b(is|iss)\s+(mahine|mahina)\b", " this month "),
    (r"\b(is|iss)\s+(hafte|hafta)\b", " this week "),
    (r"\b(agle|agla)\s+(saal|sal)\b", " next year "), (r"\b(agle|agla)\s+(mahine|mahina)\b", " next month "),
    (r"\bkal\b", " yesterday "), (r"\baaj\b|\baj\b", " today "),
    # Kanglish (Roman)
    (r"\bmonne\b|\bmonnay\b", " day before yesterday "), (r"\bninne\b|\bninnay\b|\bnenne\b", " yesterday "),
    (r"\bivattu\b|\bivathu\b|\bindu\b", " today "),
    (r"\b(kaleda|kalada|hoda|hodha|hogida)\s+(varsha|varsa|varusha|year)\b", " last year "),
    (r"\b(kaleda|kalada|hoda|hodha)\s+(tingalu|tingala|thingalu|month)\b", " last month "),
    (r"\b(kaleda|kalada|hoda|hodha)\s+(vaara|vara|week)\b", " last week "),
    (r"\bee\s+(varsha|varsa|year)\b", " this year "), (r"\bee\s+(tingalu|thingalu|tingala|month)\b", " this month "),
    (r"\bmundina\s+(varsha|year)\b", " next year "),
    # English slang
    (r"\blast\s+yr\b|\blst\s+year\b", " last year "), (r"\bystrday\b|\byesterdy\b|\byday\b|\byest\b", " yesterday "),
    (r"\btday\b|\btoday's\b", " today "),
]
_EN_MONTHS = [m.lower() for m in L.MONTHS["en-IN"]]


def _fix_month_typos(s: str) -> str:
    def fix(m: re.Match) -> str:
        w = m.group(0)
        lw = w.lower()
        if lw in ROMAN_MONTHS:
            return " " + L.MONTHS["en-IN"][ROMAN_MONTHS[lw] - 1] + " "
        if len(lw) >= 6 and lw not in _EN_MONTHS:
            close = difflib.get_close_matches(lw, _EN_MONTHS, n=1, cutoff=0.84)
            if close:
                return " " + close[0].title() + " "
        return w
    return re.sub(r"[A-Za-z]+", fix, s)


def to_english_dates(text: str, route: bool = False) -> str:
    """Hindi / Kannada (both scripts), Hinglish / Kanglish date words, month spellings and digits -> English words
    resolve_when understands. With route=True, "Nov 26" (a month and a two-digit number, no other year) means
    November 2026: rooms are months, so a bare two-digit number after a month is read as the year."""
    s = (text or "").translate(_DIGITS)
    for i, names in enumerate(zip(L.MONTHS["hi-IN"], L.MONTHS["kn-IN"])):
        for n in names:
            s = s.replace(n, f" {L.MONTHS['en-IN'][i]} ")
    for a, m in L.MONTH_ALIASES.items():
        if not a.isascii():
            s = s.replace(a, f" {L.MONTHS['en-IN'][m - 1]} ")
    for pat, en in RELATIVE:
        s = re.sub(pat, en, s, flags=re.I)
    s = _fix_month_typos(s)
    # "Diwali 2026 ge" / "2026 mein" / "2026 ರಲ್ಲಿ": case endings glued to a year or day
    s = re.sub(r"\b((?:19|20)\d{2})(?:ge|alli|nalli|ralli|mein|me|ka|ki|ke|wala|wali|wale)\b", r"\1", s, flags=re.I)
    if route and not re.search(r"\b(19|20|21)\d{2}\b", s):
        s = re.sub(r"\b(" + "|".join(L.MONTHS["en-IN"]) + r"|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\.?\s+'?(\d{2})\b(?!\s*(st|nd|rd|th)\b)",
                   lambda m: f"{m.group(1)} 20{m.group(2)}", s, flags=re.I)
    return " ".join(s.split())


# Words to drop from a place before the core's resolve_place reads the rest as an event name.
PLACE_FILLER = re.compile(
    r"\b(bhai|bhaiya|yaar|yar|please|plz|pls|mujhe|humko|hume|hamein|mereko|wale|wala|wali|waale|waala|waali|"
    r"room|kamra|kamre|mein|me|le|chalo|chal|chalte|jao|jana|jaana|hai|ko|dikhao|dikha|do|de|dena|ki|ka|ke|"
    r"karkondu|karkond|kardukondu|karedukondu|hogu|hogi|hogona|ge|ige|alli|nodu|nodona|thorsu|torsu|torisu|"
    r"nanna|nannannu|namma|i|wanna|want|to|see|what|we|did|do|happened|in|that|show|me|take|go|the|let's|lets|"
    r"can|you|could|would|like|visit|open|kholo|khol|wapas|again|once|more|ek|baar|ondu|sala)\b", re.I)


def clean_place(text: str) -> str:
    """Strip Hinglish / Kanglish / chatty filler around a place, keep dates and names: 'bhai mujhe Diwali wale room
    mein le chalo' -> 'Diwali'; 'I wanna see what we did last Holi' -> 'last Holi'."""
    s = to_english_dates(text, route=True)
    keep = PLACE_FILLER.sub(" ", s)
    keep = re.sub(r"[^\w\s'-]", " ", keep)
    keep = " ".join(keep.split())
    return keep or s
