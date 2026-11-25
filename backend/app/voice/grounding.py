"""Grandma's accuracy checks (PRD "How accuracy is protected").

The model returns {"sentences": [{"text", "memory_ids"}]}. `check()` rejects the output when
  * a memory id is not one of the supplied memories, or
  * a capitalised word (a name), a month name or a number in the text is not found in the supplied
    memories or the facts computed in code (the entity check).
The caller regenerates once, then falls back to a plain template.

Limits, stated honestly: names written in Devanagari or Kannada script cannot be told apart from ordinary
words, so for hi-IN / kn-IN the prompt asks the model to keep names exactly as spelled in the facts (usually Latin
script, which this check covers), numbers and month names are checked in every script, and the model must list
the names it used in `names`, which are checked too.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from . import lang as L

# Words that may start a sentence or appear capitalised without being an entity.
COMMON = set("""
a about above after again ah all also always am an and another any are around as at aw away back be beautiful
because been before being best better between both bright but by can could dear did do does doing done down during
each even ever every everyone everything far few first for from full fun funny gentle get give go god goes going gone
good great had happy has have he her here hers herself him himself his home how however i if in indeed inside into
is it its itself just kind last later least less let lets like listen little long look lovely lot lots made make
many may maybe me memories memory might mine more most much must my myself never new next nice no nobody none nor
not nothing now of off oh okay old on once one only or other our ours ourselves out over own perhaps please pretty
quite rather really remember right said same see she should simply since so some someone something sometimes soon
such sure sweet take tell than thank thanks that the their theirs them themselves then there these they thing
things this those though through to today together tomorrow too truly under until up us very was we well were what
when where which while who whole whom whose why will with without would wow yes yesterday yet you your yours
yourself yourselves hello hi welcome dearie child beta come let's here's there's that's it's what's who's i'm
i've i'll you're we're they're isn't wasn't didn't don't can't won't couldn't wouldn't shouldn't aren't
morning evening night afternoon day days week weeks month months year years family photo photos picture pictures
voice note notes story stories room festival time times everybody someone story's ah ha hmm achha arre
grandma grandpa mother father mom mum dad papa amma appa ajji ajja dadi dada nani nana paati thatha
sister brother aunt uncle cousin son daughter children kids baby wife husband friend friends
look looking seems seemed felt feel shared sent told says say saying wrote written recorded heard
english hindi kannada india indian
""".split())
# Spoken reactions, fillers and terms of endearment Grandma and the receptionist may use (PRD: sound like a person).
# They carry no facts, so a capitalised "Arre," or "Nodu," at the start of a sentence is never taken for a name.
INTERJECTIONS = set("""
arre arey arrey are achha accha acha achcha haan haa han hanji haanji ji oho aha ah oh ooh ohh aww aw uff uffo wah
waah hai hay hey hmm hmmm hmmmm mm mmm umm um uh er well so okay ok alright yes yeah no nah wow listen imagine
dekho dekh suno sun bas chalo chal arre-baba baba beta bete bachcha bachche bitiya munna munni lalla
nodu nodi sari saari houdu haudu ayyo ayyayyo aiyo ayyayo aiyyo kanda kandaa kanna maga magu putta chinna chinnu
paapa papa ammi amma appa ajji dadi nani thatha ajja dada nana hehe haha ha
""".split())
COMMON |= INTERJECTIONS


def _romanized_lexicon() -> set[str]:
    """Common Roman-script Hindi / Kannada words (Hinglish / Kanglish replies). A capitalised one at the start of
    a sentence ("Tumhe yaad hai?", "Nimge gotta?") is an ordinary word, not a name."""
    from .register import HINGLISH, KANGLISH
    extra = set("""
    tumhe tumhare tumhari tumko aapke aapki yaad yaadein yaadon kahaani kahani sunaaun sunao woh wo yeh ye uss us
    unhone usne humne sabne sab saare saari diye diya jalaaye jalaye chhat ghar khana mithai pataakhe phuljhadi
    ek do teen bahut thoda accha bura pyaara pyaari pyari pyaar khushi hasi hansi rona
    nimge nimma nimmappa nimmamma ninna nenapu nenapide nenapideya nenapugalu kathe hella heltini ondsala
    ella yella tumba swalpa deepa hachchidru manege mane oota sihi patakki khushi nagu nakkidvi
    """.split())
    return {w for w in (HINGLISH | KANGLISH | extra)}


ROMAN_WORDS = _romanized_lexicon()
COMMON |= ROMAN_WORDS

MONTHS_EN = [m.lower() for m in L.MONTHS["en-IN"]]
_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
_DIGITS = re.compile(r"\d+")
_DEV = str.maketrans("०१२३४५६७८९೦೧೨೩೪೫೬೭೮೯", "01234567890123456789")


def _norm_word(w: str) -> str:
    return w.lower().replace("’", "'").strip("'-")


def build_corpus(memories: Iterable[dict], facts: dict, extra: Iterable[str] = ()) -> dict[str, set]:
    """Allowed words (lower-cased), numbers and month numbers from the memories and the computed facts."""
    texts: list[str] = list(extra)

    def walk(v: Any) -> None:
        if v is None:
            return
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple, set)):
            for x in v:
                walk(x)
        else:
            texts.append(str(v))

    for m in memories:
        walk({k: m.get(k) for k in ("title", "text", "summary", "author", "teller", "festival", "transcript",
                                    "people", "event_name", "event_date", "caption")})
    walk(facts)
    # A festival may be said by any of its names ("Deepavali", "दीपावली" for Diwali): same fact, not a new one.
    from ..ai.facts import FESTIVALS, match_festival
    for fest in {match_festival(str(m.get("festival") or "")) for m in memories} | \
            {match_festival(str(f)) for f in facts.get("festivals") or []}:
        if fest:
            texts.extend(FESTIVALS[fest][1])
    blob = "\n".join(texts)
    words = {_norm_word(w) for w in _WORD.findall(blob)}
    # possessives: "Asha's" is allowed when "Asha" is
    words |= {w[:-2] for w in words if w.endswith("'s")}
    nums = {int(n) for n in _DIGITS.findall(blob.translate(_DEV))}
    for w in list(words):
        if w in L.EN_NUMBER_WORDS:
            nums.add(L.EN_NUMBER_WORDS[w])
    months = L.month_numbers_in(blob)
    for m in memories:
        mo = (m.get("event_date") or {}).get("month")
        if mo:
            months.add(int(mo))
    months |= {int(x) for x in facts.get("month_numbers", []) or []}
    return {"words": words, "nums": nums, "months": months, "blob": blob.lower()}


def _numbers_in(text: str) -> set[int]:
    t = text.translate(_DEV)
    nums = {int(n) for n in _DIGITS.findall(t)}
    low = t.lower()
    for w, n in L.EN_NUMBER_WORDS.items():
        if n in (0, 1, 100, 1000):      # "one evening", "a hundred times" are figures of speech
            continue
        if re.search(rf"\b{w}\b", low):
            nums.add(n)
    # compound tens "twenty-three"
    for m in re.finditer(r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[- ](one|two|three|four|five|six|seven|eight|nine)\b", low):
        nums.add(L.EN_NUMBER_WORDS[m.group(1)] + L.EN_NUMBER_WORDS[m.group(2)])
    return nums


def months_in_text(text: str) -> set[int]:
    """Months named in spoken text. English names count only when capitalised ("you may", "march on")."""
    found = {i + 1 for i, n in enumerate(L.MONTHS["en-IN"]) if re.search(rf"\b{n}\b", text)}
    for lg in ("hi-IN", "kn-IN"):
        found |= {i + 1 for i, n in enumerate(L.MONTHS[lg]) if L.indic_word_in(n, text)}
    found |= {m for a, m in L.MONTH_ALIASES.items() if not a.isascii() and L.indic_word_in(a, text)}
    return found


def entity_problems(text: str, corpus: dict[str, set], names: Iterable[str] = ()) -> list[str]:
    """Problems with one piece of spoken text (empty list = grounded)."""
    problems: list[str] = []
    for m in _WORD.finditer(text):
        w = m.group(0)
        if not w[0].isupper():
            continue
        lw = _norm_word(w)
        base = lw[:-2] if lw.endswith("'s") else lw
        if base in COMMON or lw in COMMON or base in corpus["words"] or lw in corpus["words"]:
            continue
        if base in MONTHS_EN:
            continue  # months are checked below by number
        problems.append(f"name not in memories: {w}")
    allowed_nums = corpus["nums"] | {1}
    for n in _numbers_in(text):
        if n not in allowed_nums:
            problems.append(f"number not in memories: {n}")
    for mo in months_in_text(text):
        if mo not in corpus["months"]:
            problems.append(f"month not in memories: {L.MONTHS['en-IN'][mo - 1]}")
    for n in names or ():
        n = str(n).strip()
        if n and n.lower() not in corpus["blob"]:
            problems.append(f"declared name not in memories: {n}")
    return problems


def check(output: Any, alias_to_id: dict[str, str], corpus: dict[str, set]) -> tuple[list[dict], list[str]]:
    """Validate model JSON. Returns (sentences with real memory ids, problems)."""
    problems: list[str] = []
    if not isinstance(output, dict) or not isinstance(output.get("sentences"), list) or not output["sentences"]:
        return [], ["output is not {sentences:[...]}"]
    out: list[dict] = []
    for s in output["sentences"]:
        if not isinstance(s, dict) or not str(s.get("text") or "").strip():
            continue
        text = " ".join(str(s["text"]).split())
        ids: list[str] = []
        for a in s.get("memory_ids") or []:
            a = str(a).strip()
            real = alias_to_id.get(a) or (a if a in alias_to_id.values() else None)
            if not real:
                problems.append(f"unknown memory id: {a}")
            elif real not in ids:
                ids.append(real)
        if re.search(r"\bm\d{1,3}\b", text):
            problems.append("memory ids (m1, m2...) must never be spoken; put them only in memory_ids")
        problems += entity_problems(text, corpus, s.get("names") or [])
        out.append({"text": text, "memory_ids": ids})
    if not out:
        problems.append("no sentences")
    return out, problems


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?।])\s+", " ".join((text or "").split()))
    return [p for p in parts if p.strip()]
