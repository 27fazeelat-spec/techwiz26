"""Signals that two same-topic clauses disagree: numbers, deadlines, frequencies and permission vs prohibition."""
import re
from functools import lru_cache

from config.loader import load_config

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "twelve": 12, "fifteen": 15, "thirty": 30}
STOPWORDS = set("""a an the and or of to in on at by for with from into be is are was were been must shall should may can
not no any all every each this that these those their its it they them than then only also if when where which who
whose as per up down out over under within before after during while until upon about above below more less such
same other another employee employees staff guest guests person people aurelle property properties required
yes you your our one two three four five six seven eight nine ten
report reported record recorded complete completed ensure follow use used take taken keep kept held hold provide
make made give check checked inform informed end part time least minimum maximum""".split())
# People named in a clause are actors, not topics: two rules that both mention the Duty Manager are not
# therefore about the same thing.
ACTOR_TOKENS = {"dutymanager", "frontofficeassociate", "roomattendant"}
TIME_OF_DAY = re.compile(r"\b([01]\d|2[0-3]):([0-5]\d)\b")
UNITS = r"(days?|hours?|minutes?|weeks?|months?|years?|%|°c|characters?|kg|rooms?|nights?)"
NUMBER_NEAR_UNIT = re.compile(rf"\b(\d+(?:,\d{{3}})*(?:\.\d+)?|{'|'.join(NUMBER_WORDS)})\s*(?:[a-z-]+\s+){{0,3}}?{UNITS}(?![a-z])", re.I)
MONEY = re.compile(r"\bUSD\s?(\d[\d,]*(?:\.\d+)?)", re.I)
PROHIBITION = re.compile(r"\b(must not|shall not|must never|never|prohibited|not permitted|is not allowed|are not allowed)\b", re.I)
PERMISSION = re.compile(r"\b(may|can)\b(?!\s+only)", re.I)
RESTRICTION = re.compile(r"\b(may only|only by|only when|only after|only if|only at)\b", re.I)


@lru_cache(maxsize=1)
def _synonyms():
    pairs = []
    for canonical, variants in load_config("glossary")["synonyms"].items():
        token = re.sub(r"[^a-z]", "", canonical.lower())
        for v in [canonical, *variants]:
            pairs.append((re.compile(rf"\b{re.escape(v.lower())}\b"), f" {token} "))
    return sorted(pairs, key=lambda p: -len(p[0].pattern))


def _stem(word):
    """Crude but consistent stemming: waive/waived -> waiv, carry/carried -> carry, rooms -> room."""
    for suffix, repl in (("ied", "y"), ("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)] + repl
            break
    return word[:-1] if word.endswith("e") and len(word) > 4 else word


def glossary_tokens():
    """Curated topic terms (stemmed the same way as topic words), excluding actors."""
    return {_stem(re.sub(r"[^a-z]", "", c.lower())) for c in load_config("glossary")["synonyms"]} - _actors()


def _actors():
    return {_stem(t) for t in ACTOR_TOKENS}


def topic_words(text):
    """Topic words of a clause: glossary terms normalised, actors and generic verbs removed, times kept."""
    text = (text or "").lower()
    times = {f"t{h}{m}" for h, m in TIME_OF_DAY.findall(text)}
    for pattern, token in _synonyms():
        text = pattern.sub(token, text)
    words = {_stem(w) for w in re.findall(r"[a-z][a-z-]{2,}", text) if w not in STOPWORDS}
    return (words - _actors()) | times


def topic_similarity(a, b, idf=None):
    """IDF-weighted overlap coefficient of topic words.

    Rare, specific words ("fire drill", "late check-out fee") count for more than common ones, and the
    overlap is measured against the shorter clause, so a short FAQ answer can still match a policy clause.
    """
    wa, wb = topic_words(a), topic_words(b)
    if not wa or not wb:
        return 0.0, set()
    weight = (lambda w: idf.get(w, 1.0)) if idf else (lambda w: 1.0)
    shared = wa & wb
    score = sum(weight(w) for w in shared) / min(sum(weight(w) for w in wa), sum(weight(w) for w in wb))
    return score, shared


def _num(word):
    word = word.lower()
    return NUMBER_WORDS.get(word) if word in NUMBER_WORDS else float(word.replace(",", ""))


def deadline_minutes(text):
    """Reporting / action deadline in minutes, or None."""
    t = (text or "").lower()
    if re.search(r"\bimmediately\b", t):
        return 0
    m = re.search(r"\bwithin (\d+|[a-z]+) (minute|hour|day|working day)s?\b", t)
    if m and (m.group(1).isdigit() or m.group(1) in NUMBER_WORDS):
        factor = {"minute": 1, "hour": 60, "day": 1440, "working day": 1440}[m.group(2)]
        return _num(m.group(1)) * factor
    if re.search(r"\b(before|by) the end of the shift\b", t):
        return 480
    if re.search(r"\bsame day\b", t):
        return 1440
    return None


def frequency_months(text):
    t = (text or "").lower()
    if re.search(r"\b(annual|annually|every year|once a year|yearly)\b", t):
        return 12
    m = re.search(r"\bevery (\d+|[a-z]+) months?\b", t)
    if m and (m.group(1).isdigit() or m.group(1) in NUMBER_WORDS):
        return _num(m.group(1))
    if re.search(r"\b(six-monthly|twice a year)\b", t):
        return 6
    if re.search(r"\bmonthly\b", t):
        return 1
    return None


def numbers(text):
    """{unit: set(values)}: numbers with a unit up to three words later ("5 unused annual leave days")."""
    out = {}
    for m in NUMBER_NEAR_UNIT.finditer(text or ""):
        unit = m.group(2).lower()
        unit = unit if unit in ("%", "°c") else unit.rstrip("s")
        out.setdefault(unit, set()).add(_num(m.group(1)))
    for m in MONEY.finditer(text or ""):
        out.setdefault("usd", set()).add(float(m.group(1).replace(",", "")))
    return out


OBLIGATION = re.compile(r"\b(must|shall|is required|are required)\b", re.I)


def polarity(text, strength):
    """'prohibits' | 'restricts' | 'permits' | 'obliges', from the clause's main verb.

    "Employees may accept gifts up to USD 25; anything above must be declared" permits: the permission
    comes first and the obligation only qualifies it.
    """
    if PROHIBITION.search(text):
        return "prohibits"
    if RESTRICTION.search(text):
        return "restricts"
    perm, must = PERMISSION.search(text), OBLIGATION.search(text)
    if perm and (must is None or perm.start() < must.start()):
        return "permits"
    return "obliges"


def differences(a, b):
    """List of disagreement signals between two requirement dicts on the same topic."""
    out = []
    na, nb = numbers(a["text"]), numbers(b["text"])
    for unit in set(na) & set(nb):
        if na[unit] != nb[unit] and not (na[unit] & nb[unit]):
            out.append({"type": "number", "unit": unit, "left": sorted(na[unit]), "right": sorted(nb[unit])})
    da, db = deadline_minutes(a["text"]), deadline_minutes(b["text"])
    if da is not None and db is not None and da != db:
        out.append({"type": "deadline", "unit": "minutes", "left": da, "right": db})
    fa, fb = frequency_months(a["text"]), frequency_months(b["text"])
    if fa is not None and fb is not None and fa != fb:
        out.append({"type": "frequency", "unit": "months", "left": fa, "right": fb})
    pa, pb = polarity(a["text"], a["strength"]), polarity(b["text"], b["strength"])
    if (pa == "permits") != (pb == "permits"):          # one side allows what the other forbids or requires
        out.append({"type": "permission", "left": pa, "right": pb})
    return out


def stricter(diff, a_first=True):
    """Which side ('left'/'right') is stricter for a difference, or None if it cannot be said."""
    t = diff["type"]
    if t in ("deadline", "frequency"):
        return "left" if diff["left"] < diff["right"] else "right"
    if t == "permission":
        rank = {"prohibits": 3, "restricts": 2, "obliges": 1, "permits": 0}
        return "left" if rank[diff["left"]] > rank[diff["right"]] else "right"
    return None
