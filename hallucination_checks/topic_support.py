"""Do the approved documents cover a topic? Decided by Python from the stored passages, never by a GenAI model.

A topic is reduced to its key words. Each approved passage (active, not quarantined) is scored by the share of
those words it contains, with rare words counting more than common ones (inverse document frequency). The best
passage decides the outcome:

    supported      the sources cover the topic; training may be generated and will be validated as usual
    review         partly covered; a person must decide before anything is written
    unsupported    nothing approved covers it; the application refuses rather than invent company rules
"""
import math
import re
from dataclasses import dataclass, field

STOPWORDS = set("""a an and are as at be been but by can could do does for from had has have how i if in into is it its
may might must not of on or our shall should so than that the their them then there these they this to under up upon
was we were what when where which who whom why will with within without would you your""".split())


@dataclass
class TopicResult:
    topic: str
    status: str                                   # supported | review | unsupported
    score: float                                  # best passage's weighted share of the topic's key words (0-1)
    terms: list = field(default_factory=list)
    matches: list = field(default_factory=list)   # [{"ref", "doc_id", "section_id", "text", "score", "requirement"}]
    message: str = ""


def _stem(word):
    """A light stemmer: scans, scanning and scanned all become "scan"."""
    for suffix in ("ing", "ies", "es", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
            if suffix in ("ing", "ed") and len(word) > 3 and word[-1] == word[-2] and word[-1] not in "aeiouls":
                word = word[:-1]                                    # scann -> scan, but keep "fill", "pass"
            return word
    return word


def terms(text, extra_stopwords=()):
    stop = STOPWORDS | {w.lower() for w in extra_stopwords}
    words = re.findall(r"[a-z][a-z0-9]+", (text or "").lower())
    return list(dict.fromkeys(_stem(w) for w in words if len(w) > 2 and w not in stop))


def assess(topic, passages, supported_at=0.6, review_at=0.3, max_matches=6, extra_stopwords=()):
    """passages: iterable of dicts with "ref", "doc_id", "section_id", "text" and optional "requirement"."""
    wanted = terms(topic, extra_stopwords)
    if not wanted:
        return TopicResult(topic, "unsupported", 0.0, [], [], "The topic has no words to look for.")
    passages = list(passages)
    stemmed = [set(terms(p["text"], extra_stopwords)) for p in passages]
    n = max(len(passages), 1)
    weight = {t: math.log((n + 1) / (1 + sum(t in s for s in stemmed))) + 1 for t in wanted}
    total = sum(weight.values())
    scored = []
    for p, words in zip(passages, stemmed):
        share = sum(weight[t] for t in wanted if t in words) / total
        if share > 0:
            scored.append((share, p))
    scored.sort(key=lambda x: (-x[0], x[1].get("ref", "")))
    best = scored[0][0] if scored else 0.0
    matches = [{**p, "score": round(s, 2)} for s, p in scored[:max_matches] if s >= review_at]
    if best >= supported_at:
        status, message = "supported", "The approved documents cover this topic."
    elif best >= review_at:
        status, message = "review", "Only partly covered by the approved documents. A person should decide before any training is written."
    else:
        status, message = "unsupported", ("No approved document covers this topic. Training about it would have to invent "
                                          "company rules, so none will be generated.")
    return TopicResult(topic, status, round(best, 2), wanted, matches, message)
