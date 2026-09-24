"""Document metadata: header table first, then the upload form, then heuristics.

Every field records where its value came from, so a reviewer can see which values
were read from the document and which were guessed.
"""
import re
from datetime import date, datetime

LABELS = {
    "document id": "doc_id", "doc id": "doc_id", "document number": "doc_id",
    "title": "title",
    "version": "version", "revision": "version",
    "status": "status",
    "effective date": "effective_date", "effective from": "effective_date",
    "review / expiry date": "expiry_date", "expiry date": "expiry_date", "review date": "expiry_date",
    "owner department": "owner_department", "department": "owner_department", "owner": "owner_department",
    "category": "category", "document type": "category",
    "applies to": "applies_to", "audience": "applies_to",
    "supersedes": "supersedes", "replaces": "supersedes",
}
FIELDS = ["doc_id", "title", "version", "status", "effective_date", "expiry_date",
          "owner_department", "category", "applies_to", "supersedes"]
DOC_ID = re.compile(r"(?<![A-Za-z0-9-])([A-Z]{2,5}(?:-[A-Z]{2,4})?-\d{2})(?![0-9A-Za-z])")   # "GDP-01_v3.0.pdf" too
VERSION = re.compile(r"(?:^|[\s_])v(?:ersion)?\s?(\d+(?:\.\d+)*(?:-[A-Za-z]+)?)", re.I)
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def parse_date(value):
    if isinstance(value, date):
        return value
    text = (value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", text)
    if m and m.group(2).lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", text)
    if m and m.group(1).lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    return None


def version_key(version):
    """'2.10' > '2.9'; '3.0-DRAFT' sorts as 3.0."""
    nums = re.findall(r"\d+", (version or "").split("-")[0])
    return tuple(int(n) for n in nums) or (0,)


def _label_field(text):
    return LABELS.get(text.strip().rstrip(":").lower())


def read_header(parsed, scan_limit=40):
    """Return (values, consumed_block_indexes) from a metadata table or 'Label: value' lines."""
    values, consumed = {}, set()
    for i, block in enumerate(parsed.blocks[:scan_limit]):
        if block.kind == "heading" and values:
            break
        if block.kind == "table_row" and len(block.cells) >= 2:
            field = _label_field(block.cells[0])
            if field and field not in values:
                values[field] = block.cells[1].strip()
                consumed.add(i)
        elif block.kind in ("paragraph", "letterhead") and len(block.clean) <= 80:
            m = re.match(r"^([A-Za-z /]+):\s*(.+)$", block.clean)
            field = _label_field(m.group(1)) if m else None
            if field and field not in values:
                values[field] = m.group(2).strip()
                consumed.add(i)
        elif block.kind in ("paragraph", "letterhead") and len(block.clean) <= 600:
            pairs = _label_run(block.clean)            # "Label: value" lines a PDF reader joined into one paragraph
            if pairs:
                for field, value in pairs:
                    values.setdefault(field, value)
                consumed.add(i)
    return values, consumed


_LABEL_AT = re.compile(r"(?:^|(?<=\s))(" + "|".join(sorted((re.escape(k) for k in LABELS), key=len, reverse=True))
                       + r")\s*:\s*", re.I)


def _label_run(text):
    """[(field, value)] when the text is nothing but two or more known 'Label: value' pairs, else []."""
    marks = list(_LABEL_AT.finditer(text))
    if len(marks) < 2 or marks[0].start() != 0:
        return []
    pairs = []
    for m, nxt in zip(marks, marks[1:] + [None]):
        value = text[m.end(): nxt.start() if nxt else len(text)].strip()
        if not value:
            return []
        pairs.append((_label_field(m.group(1)), value))
    return pairs


def heuristics(parsed, filename):
    guesses = {}
    title_block = next((b for b in parsed.blocks if b.kind == "title"), None)
    if title_block:
        guesses["title"] = title_block.clean
    elif parsed.properties.get("title"):
        guesses["title"] = parsed.properties["title"]
    sources = [parsed.properties.get("subject", ""), filename or "", guesses.get("title", "")]
    for text in sources:
        m = DOC_ID.search(text)
        if m:
            guesses["doc_id"] = m.group(1)
            break
    for text in sources:
        m = VERSION.search(text.replace(".docx", "").replace(".pdf", ""))
        if m:
            guesses["version"] = m.group(1)
            break
    return guesses


def extract_metadata(parsed, filename, form=None, category_synonyms=None, draft_markers=()):
    """Merge header > form > heuristics. Returns (metadata, sources, warnings, consumed_blocks)."""
    header, consumed = read_header(parsed)
    form = {k: v for k, v in (form or {}).items() if v not in (None, "")}
    guesses = heuristics(parsed, filename)

    meta, sources, warnings = {}, {}, []
    for field in FIELDS:
        if field in header and header[field] != "":
            meta[field], sources[field] = header[field], "header"
            if field in form and str(form[field]).strip() != header[field]:
                warnings.append(f"{field}: the document says '{header[field]}' but the upload form says "
                                f"'{form[field]}'; the document value was used.")
        elif field in form:
            meta[field], sources[field] = form[field], "form"
        elif field in guesses:
            meta[field], sources[field] = guesses[field], "heuristic"
            warnings.append(f"{field} was inferred ('{guesses[field]}'); please confirm it.")

    for field in ("effective_date", "expiry_date"):
        raw = meta.get(field)
        if raw and not isinstance(raw, date):
            parsed_date = parse_date(str(raw))
            if parsed_date is None:
                warnings.append(f"{field} '{raw}' is not a recognised date and was ignored.")
            meta[field] = parsed_date

    if str(meta.get("supersedes", "")).strip().lower() in ("", "none", "n/a", "-"):
        meta["supersedes"] = None
    if meta.get("category") and category_synonyms:
        meta["category"] = category_synonyms.get(meta["category"], meta["category"])

    status_text = f"{meta.get('status', '')} {meta.get('version', '')} {parsed.watermark}".lower()
    meta["is_draft"] = any(marker in status_text for marker in draft_markers)
    return meta, sources, warnings, consumed
