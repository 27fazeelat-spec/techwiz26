"""Deterministic prompt-injection and adversarial-content scanner (SRS Steps 42-43).

Uploaded documents are data. Anything in them that tries to act as an instruction to an AI system,
impersonates the system, hides text from human readers or smuggles structure into prompts is
recorded as a finding. Chunks with a visible attack are quarantined: never sent to Gemini and never
used for requirements. Hidden text is always excluded from generation and extraction (see
Chunk.source_text) but kept in raw_text as evidence.
"""
import base64
import binascii
import re
from dataclasses import dataclass, field

from config.loader import load_config
from document_processing.models import ZERO_WIDTH, normalise_text

# Base64 split across wrapped lines: several long runs, possibly ending in a short final piece.
BASE64_RUN = re.compile(r"(?:[A-Za-z0-9+/]{8,}\s?){2,}[A-Za-z0-9+/]*={0,2}")


@dataclass
class Finding:
    chunk_id: str | None
    technique: str
    pattern: str
    severity: str
    action: str
    excerpt: str
    decoded: str = ""


@dataclass
class ScanResult:
    findings: list = field(default_factory=list)
    quarantined: set = field(default_factory=set)      # chunk_ids


def _compiled():
    cfg = load_config("security_patterns")
    return {name: (spec, [re.compile(p, re.I | re.S) for p in spec["patterns"]])
            for name, spec in cfg["families"].items()}, cfg


def _match_families(text, families):
    """Yield (family, pattern, match) for every family that matches the text."""
    for name, (spec, patterns) in families.items():
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                yield name, spec, pattern.pattern, m
                break


def _excerpt(text, m, width=90):
    start = max(0, m.start() - 20)
    return normalise_text(text[start:start + width])


def _decode_base64_runs(text, min_length):
    for m in BASE64_RUN.finditer(text):
        blob = re.sub(r"\s", "", m.group(0))
        if len(blob) < min_length:
            continue
        blob += "=" * (-len(blob) % 4)
        try:
            decoded = base64.b64decode(blob, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded.isprintable() and sum(c.isalpha() for c in decoded) > len(decoded) * 0.6:
            yield m, decoded


def scan_chunk(chunk, families, cfg):
    """Return findings for one chunk dict (text, raw_text, hidden_text, chunk_id)."""
    findings = []
    chunk_id = chunk["chunk_id"]
    raw = chunk.get("raw_text") or chunk["text"]
    hidden = chunk.get("hidden_text") or ""
    visible = chunk["text"].replace(normalise_text(hidden), "") if hidden else chunk["text"]

    # 1. Hidden text: always excluded; its content decides the severity.
    if hidden:
        attack = next(_match_families(normalise_text(hidden), families), None)
        findings.append(Finding(chunk_id, "hidden_text", attack[2] if attack else "hidden-formatting",
                                "high" if attack else "medium", "hidden_text_excluded", normalise_text(hidden)[:200]))

    # 2. Visible instructions and structure attacks.
    for name, spec, pattern, m in _match_families(visible, families):
        findings.append(Finding(chunk_id, name, pattern, spec["severity"], spec["action"], _excerpt(visible, m)))

    # 3. Obfuscation: the chunk text is already cleaned of zero-width characters, so an attack found
    #    above while the raw text contains them was deliberately disguised from simple keyword filters.
    if ZERO_WIDTH.search(raw):
        spec = cfg["obfuscation"]
        for f in findings:
            if f.technique != "hidden_text":
                f.technique, f.decoded = "obfuscation", f.excerpt
                f.severity, f.action = spec["severity"], spec["action"]

    # 4. Encoded instructions.
    enc = cfg["encoded"]
    for m, decoded in _decode_base64_runs(visible, enc["min_length"]):
        attack = next(_match_families(decoded, families), None)
        findings.append(Finding(chunk_id, "encoded_instruction", attack[2] if attack else "base64",
                                enc["severity"] if attack else "medium",
                                enc["action"] if attack else "flag", _excerpt(visible, m, 60), decoded=decoded[:300]))
    return findings


def scan_document(chunks, is_draft=False, watermark="", properties=None):
    """Scan all chunks of one document version. chunks: list of dicts; properties: the file's own metadata fields."""
    families, cfg = _compiled()
    result = ScanResult()
    if is_draft:
        result.findings.append(Finding(None, "draft_document", "document-status", "medium", "not_a_source",
                                       (watermark or "Document marked as draft / not approved")[:200]))
    # File properties (DOCX comments, keywords, subject...) are invisible in the page but travel with the file.
    # They never reach a prompt; an instruction hidden there is still recorded so a reviewer sees the attempt.
    for field, value in (properties or {}).items():
        text = normalise_text(str(value or ""))
        attack = next(_match_families(text, families), None)
        if attack:
            result.findings.append(Finding(None, "metadata_instruction", attack[2], "high", "metadata_excluded",
                                           f"{field}: {_excerpt(text, attack[3])}"))
    for chunk in chunks:
        for f in scan_chunk(chunk, families, cfg):
            result.findings.append(f)
            if f.action == "quarantine":
                result.quarantined.add(f.chunk_id)
    return result
