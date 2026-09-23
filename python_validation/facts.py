"""Fact extraction shared by the hallucination and quiz checks: numbers with units, money, times."""
import re

from role_matrix.extractor import FACT_MONEY, FACT_NUMBER, FACT_TIME, NUMBER_WORDS

WORD = re.compile(r"[a-z0-9][a-z0-9'-]{2,}")
NUMBER = re.compile(r"\b(\d+(?:,\d{3})*(?:\.\d+)?)\b")
STOPWORDS = {"must", "with", "that", "this", "from", "into", "they", "their", "have", "will", "your", "when",
             "which", "there", "been", "were", "what", "about", "after", "before", "should", "every", "only",
             "than", "then", "them", "also", "each", "such", "under", "over", "within", "guest", "guests",
             "employee", "employees", "staff", "true", "false", "the", "and", "for", "are", "any", "all", "not"}
# Onboarding phrases that mean the same thing ("on their first day" = "Day 1").
EQUIVALENT = [(re.compile(r"\b(first working day|first day|day one|day 1)\b"), " dayone "),
              (re.compile(r"\b(first week|week one|week 1)\b"), " weekone "),
              (re.compile(r"\b(first two weeks|week two|week 2)\b"), " weektwo ")]


def _normalise(text):
    text = (text or "").lower()
    for pattern, token in EQUIVALENT:
        text = pattern.sub(token, text)
    return text


def facts(text):
    """Set of normalised facts, e.g. {'65 °c', '2 hour', 'usd 50', '12:00'}."""
    found = set()
    for m in FACT_NUMBER.finditer(text or ""):
        raw = m.group(1).lower()
        value = NUMBER_WORDS.get(raw) or float(raw.replace(",", ""))
        found.add(f"{value:g} {m.group(2).lower().rstrip('s')}")
    for m in FACT_MONEY.finditer(text or ""):
        found.add(f"usd {float(m.group(1).replace(',', '')):g}")
    for m in FACT_TIME.finditer(text or ""):
        found.add(m.group(0))
    return found


def unsupported(claim, source):
    """Facts in claim that the source does not state.

    A fact counts as stated when the source has it in the same form ("5 days"), or when the source
    contains the same number and the same unit word separately ("5 unused annual leave days").
    """
    missing = facts(claim) - facts(source)
    if not missing:
        return set()
    src = (source or "").lower()
    numbers = {f"{float(n.replace(',', '')):g}" for n in NUMBER.findall(src)}
    numbers |= {f"{v:g}" for w, v in NUMBER_WORDS.items() if re.search(rf"\b{w}\b", src)}
    still = set()
    for fact in missing:
        value, _, unit = fact.partition(" ")
        if fact.startswith("usd ") or ":" in fact:
            still.add(fact)
        elif not (value in numbers and unit and re.search(rf"\b{re.escape(unit.rstrip('s'))}", src)):
            still.add(fact)
    return still


def content_words(text):
    return {w for w in WORD.findall(_normalise(text)) if w not in STOPWORDS}


def overlap(claim, source):
    words = content_words(claim)
    return len(words & content_words(source)) / len(words) if words else 1.0
