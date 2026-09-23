"""Requirement extraction from chunk text (SRS Step 11).

A requirement is one sentence carrying an obligation, a recommendation or a permission.
Informational sentences, questions and table rows are not requirements. Every decision comes from
the rules in config/extraction.yaml, so each classification can be explained and changed.
"""
import re
from dataclasses import dataclass, field

from config.loader import load_config

SENTENCE_END = re.compile(r"(?<=[.!])\s+(?=[A-Z\"'(])")
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
UNIT = r"(%|°C|minutes?|hours?|days?|nights?|weeks?|months?|years?|kg|characters?|rooms?|shifts?)"
FACT_NUMBER = re.compile(rf"\b(\d+(?:,\d{{3}})*(?:\.\d+)?|{'|'.join(NUMBER_WORDS)})[\s-]?{UNIT}(?![a-z])", re.I)
FACT_MONEY = re.compile(r"\bUSD\s?(\d[\d,]*(?:\.\d+)?)")
FACT_TIME = re.compile(r"\b([01]\d|2[0-3]):([0-5]\d)\b")
DOC_REF = re.compile(r"\b([A-Z]{2,5}(?:-[A-Z]{2,4})?-\d{2})\b(?:\s+Section\s+(\d+(?:\.\d+)*))?")
ANNEX_REF = re.compile(r"\bAnnex\s+([A-Z0-9]+)\b")
NAMED_REF = re.compile(r"\b(?:the|see)\s+((?:[A-Z][A-Za-z&]+\s)+)(SOP|Policy|Procedure)\b")


@dataclass
class ExtractedRequirement:
    text: str
    modality: str                    # the phrase that decided the strength, e.g. "must"
    strength: str                    # mandatory | recommended | optional
    req_type: str
    mandatory: bool
    subject: str
    due_stage: str
    stage_source: str                # text | default
    priority: str
    competency: str
    assessment_type: str
    condition: dict | None
    facts: list = field(default_factory=list)
    cross_refs: list = field(default_factory=list)


class Rules:
    """Compiled extraction rules."""

    def __init__(self):
        cfg = load_config("extraction")
        self.cfg = cfg
        self.modality = [(strength, [re.compile(p, re.I) for p in patterns])
                         for strength, patterns in cfg["modality"].items()]
        self.types = [(t, [re.compile(p, re.I) for p in patterns]) for t, patterns in cfg["types"].items()]
        self.stages = [(s, [re.compile(p, re.I) for p in patterns]) for s, patterns in cfg["stages"].items()]
        self.conditions = [(re.compile(c["pattern"], re.I), c) for c in cfg["conditions"]]
        self.competencies = {name: [k.lower() for k in words] for name, words in cfg["competencies"].items()}
        self.high_patterns = [re.compile(p, re.I) for p in cfg["priority"]["high_patterns"]]


def split_sentences(text):
    """Sentences from chunk text. Lines are separate blocks (paragraphs, list items, table rows)."""
    for line in text.split("\n"):
        line = line.strip()
        if not line or " | " in line:          # table rows are reference data, not clauses
            continue
        for sentence in SENTENCE_END.split(line):
            sentence = sentence.strip()
            if sentence and not sentence.endswith("?") and len(sentence.split()) >= 4:
                yield sentence


def classify_strength(sentence, rules):
    """Strongest obligation group present; within it, the earliest phrase (the clause's main verb)."""
    for strength, patterns in rules.modality:
        matches = [m for m in (p.search(sentence) for p in patterns) if m]
        if matches:
            return strength, min(matches, key=lambda m: m.start())
    return None, None


def classify_type(sentence, strength, rules):
    if strength == "recommended":
        return "Recommended"
    if strength == "optional":
        return "Optional"
    for req_type, patterns in rules.types:
        if any(p.search(sentence) for p in patterns):
            return req_type
    return "Must Know"


def detect_condition(sentence, rules):
    for pattern, spec in rules.conditions:
        m = pattern.search(sentence)
        if not m:
            continue
        value = spec["value"]
        if isinstance(value, str) and "{" in value:
            value = value.format(None, *m.groups())
            if spec.get("transform") == "slug":
                value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return {"field": spec["field"], "op": spec["op"], "value": value, "text": m.group(0)}
    return None


def detect_stage(sentence, req_type, priority, rules):
    for stage, patterns in rules.stages:
        if any(p.search(sentence) for p in patterns):
            return stage, "text"
    default = rules.cfg["default_stage"][req_type]
    if isinstance(default, dict):
        default = default.get(priority, default["default"])
    return default, "default"


def detect_competency(sentence, context, rules):
    s, c = sentence.lower(), context.lower()
    scores = {name: 2 * sum(k in s for k in words) + sum(k in c for k in words)
              for name, words in rules.competencies.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "General"


def detect_priority(sentence, mandatory, competency, stage, req_type, rules):
    if not mandatory:
        return "Low"
    p = rules.cfg["priority"]
    if (competency in p["high_competencies"] or stage in p["high_stages"] or req_type == "Must Acknowledge"
            or any(r.search(sentence) for r in rules.high_patterns)):
        return "High"
    return "Medium"


def extract_facts(sentence, actor_names):
    facts = []
    for m in FACT_NUMBER.finditer(sentence):
        raw = m.group(1).lower()
        value = NUMBER_WORDS.get(raw) or float(raw.replace(",", ""))
        facts.append({"kind": "number", "value": value, "unit": m.group(2).lower().rstrip("s") or m.group(2),
                      "span": m.group(0)})
    for m in FACT_MONEY.finditer(sentence):
        facts.append({"kind": "number", "value": float(m.group(1).replace(",", "")), "unit": "USD", "span": m.group(0)})
    for m in FACT_TIME.finditer(sentence):
        facts.append({"kind": "time", "value": m.group(0), "unit": "time", "span": m.group(0)})
    lowered = sentence.lower()
    for actor in sorted(actor_names, key=len, reverse=True):
        if re.search(rf"\b{re.escape(actor.lower())}\b", lowered):
            facts.append({"kind": "actor", "value": actor, "unit": "actor", "span": actor})
            lowered = lowered.replace(actor.lower(), " ")
    return facts


def extract_cross_refs(sentence, own_doc_id):
    refs = []
    for m in DOC_REF.finditer(sentence):
        if m.group(1) != own_doc_id:
            refs.append({"type": "document", "doc_id": m.group(1), "section_id": m.group(2), "text": m.group(0)})
    for m in ANNEX_REF.finditer(sentence):
        refs.append({"type": "annex", "doc_id": own_doc_id, "section_id": f"Annex {m.group(1)}", "text": m.group(0)})
    for m in NAMED_REF.finditer(sentence):
        refs.append({"type": "named", "name": (m.group(1) + m.group(2)).strip(), "text": m.group(0)})
    return refs


def extract_from_chunk(text, doc_id, doc_title, heading_path, actor_names, rules=None):
    """Return ExtractedRequirement objects for one chunk's source text."""
    rules = rules or Rules()
    context = " ".join(heading_path) + " " + (doc_title or "")
    found = []
    for sentence in split_sentences(text):
        strength, m = classify_strength(sentence, rules)
        if strength is None:
            continue
        req_type = classify_type(sentence, strength, rules)
        mandatory = strength == "mandatory"
        competency = detect_competency(sentence, context, rules)
        stage, stage_source = detect_stage(sentence, req_type, "High", rules)
        priority = detect_priority(sentence, mandatory, competency, stage, req_type, rules)
        if stage_source == "default":
            stage, stage_source = detect_stage(sentence, req_type, priority, rules)
        found.append(ExtractedRequirement(
            text=sentence, modality=m.group(0).lower(), strength=strength, req_type=req_type,
            mandatory=mandatory, subject=sentence[:m.start()].strip(), due_stage=stage,
            stage_source=stage_source, priority=priority, competency=competency,
            assessment_type=rules.cfg["assessment"][req_type], condition=detect_condition(sentence, rules),
            facts=extract_facts(sentence, actor_names), cross_refs=extract_cross_refs(sentence, doc_id)))
    return found
