"""Section-aware chunking (SRS Step 7).

A chunk is the content under one section heading, split further only when it is long.
Every chunk keeps its document, version, section ID, heading path and location, so any
generated statement can be traced back to the exact place it came from.
"""
import re
from collections import Counter

from document_processing.models import normalise_text

SECTION_PATTERNS = [
    re.compile(r"^(\d+(?:\.\d+)*)\.?\s"),       # 2.1 / 3.
    re.compile(r"^(Q\d+)\."),                    # Q4.
    re.compile(r"^(Clause \d+)\b"),              # Clause 7
    re.compile(r"^(Annex [A-Z0-9]+)\b"),         # Annex A
    re.compile(r"^(Appendix(?: [A-Z0-9]+)?)\b"),
]
STANDARD_FOOTER = re.compile(r"Page\s*\d*\s*$")


def section_id_for(heading):
    text = normalise_text(heading)
    for pattern in SECTION_PATTERNS:
        m = pattern.match(text)
        if m:
            return m.group(1)
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "section"


def _location(blocks):
    pages = [b.page for b in blocks if b.page is not None]
    paras = [b.paragraph_index for b in blocks if b.paragraph_index is not None]
    if pages:
        return {"page_start": min(pages), "page_end": max(pages)}
    if paras:
        return {"paragraph_start": min(paras), "paragraph_end": max(paras)}
    return {}


def _block_text(block, clean=True):
    text = " | ".join(block.cells) if block.kind == "table_row" else block.text
    return normalise_text(text) if clean else text


def chunk_document(parsed, doc_id, version, exclude=frozenset(), max_words=350):
    """Return chunk dicts in reading order."""
    body = [(i, b) for i, b in enumerate(parsed.blocks)
            if i not in exclude and b.kind not in ("letterhead", "title", "footer")]
    has_headings = any(b.kind == "heading" for _, b in body)

    groups = []            # (section_id, heading, heading_path, [blocks])
    if has_headings:
        path, current = [], ("preamble", "", [], [])
        for _, b in body:
            if b.kind == "heading":
                if current[3]:
                    groups.append(current)
                level = max(b.level, 1)
                path = path[:level - 1] + [b.clean]
                current = (section_id_for(b.text), b.clean, list(path), [])
            else:
                current[3].append(b)
        if current[3]:
            groups.append(current)
    else:
        for n, (_, b) in enumerate(body, start=1):
            groups.append((f"para {n}", "", [], [b]))

    footers = {b.clean for b in parsed.blocks if b.kind == "footer" and not STANDARD_FOOTER.search(b.clean)}
    for text in sorted(footers):
        block = next(b for b in parsed.blocks if b.kind == "footer" and b.clean == text)
        groups.append(("footer", "Page footer", ["Page footer"], [block]))

    chunks, seen, order = [], Counter(), 0
    for section, heading, path, blocks in groups:
        parts, current, words = [], [], 0
        for b in blocks:
            n = len(_block_text(b).split())
            if current and words + n > max_words:
                parts.append(current)
                current, words = [], 0
            current.append(b)
            words += n
        if current:
            parts.append(current)

        for part in parts:
            seen[section] += 1
            order += 1
            text = "\n".join(_block_text(b) for b in part)
            chunks.append({
                "chunk_id": f"{doc_id}:{version}:{section.replace(' ', '_')}:{seen[section]}",
                "doc_id": doc_id,
                "version": version,
                "section_id": section,
                "heading": heading,
                "heading_path": path,
                "text": text,
                "raw_text": "\n".join(_block_text(b, clean=False) for b in part),
                "location": {"footer": True} if section == "footer" else _location(part),
                "order": order,
                "word_count": len(text.split()),
                "hidden_content": any(b.hidden for b in part),
                "hidden_text": " ".join(b.hidden_text for b in part if b.hidden_text).strip(),
                "quarantined": False,
            })
    return chunks
