"""PDF parsing with pdfplumber.

Produces page-referenced blocks. Headings are recognised from font weight and size
relative to the body text; tables come from ruled table detection; page footers,
rotated watermarks and hidden text (white or tiny glyphs) are identified explicitly.
"""
import io
import re
from collections import Counter

import pdfplumber

from document_processing.models import Block, ParsedDocument

FOOTER_ZONE_PT = 50          # lines starting this close to the bottom edge are page footers
PARAGRAPH_GAP_PT = 5.5       # vertical gap that starts a new paragraph
WHITE = {(1,), (1, 1, 1), (0, 0, 0, 0)}


def _rotated(obj):
    """Rotated glyphs (diagonal watermarks). pdfplumber's 'upright' flag misses non-90-degree angles."""
    if obj.get("object_type") != "char":
        return False
    m = obj.get("matrix") or (1, 0, 0, 1)
    return abs(m[1]) > 0.01 or abs(m[2]) > 0.01 or not obj.get("upright", True)


def _is_white(color):
    if color is None:
        return False
    try:
        return tuple(round(float(c), 2) for c in color) in WHITE
    except TypeError:
        return False


def _line_style(chars):
    sizes = [round(c["size"], 1) for c in chars if c["text"].strip()] or [0]
    size = Counter(sizes).most_common(1)[0][0]
    bold = sum("Bold" in c.get("fontname", "") for c in chars) > len(chars) / 2
    visible = [c for c in chars if c["text"].strip()]
    hidden = bool(visible) and all(_is_white(c.get("non_stroking_color")) or c["size"] < 3 for c in visible)
    return size, bold, hidden


NUMBERED = re.compile(r"^\d+(?:\.\d+)*\.?\s+\S")


def _heading_level(text, size, heading_sizes, body):
    """Numbering decides the level when present ("2." -> 1, "2.1" -> 2); otherwise font size does."""
    match = re.match(r"^(\d+(?:\.\d+)*)\.?\s", text)
    if match:
        return min(match.group(1).count(".") + 1, 3)
    if re.match(r"^(Annex|Appendix)\b", text):
        return 1
    if re.match(r"^(Clause \d+|Q\d+\.)", text):
        return 2
    section_sizes = [s for s in heading_sizes if s < body * 1.6]   # exclude title-sized text
    return 1 if section_sizes and size >= section_sizes[0] else 2


def _body_size(pages_lines):
    sizes = Counter()
    for lines in pages_lines:
        for line in lines:
            size, bold, hidden = _line_style(line["chars"])
            if not bold and not hidden:
                sizes[size] += len(line["text"])
    return sizes.most_common(1)[0][0] if sizes else 10


def parse_pdf(data):
    warnings, watermark_chars = [], []
    raw_pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        properties = {k.lower(): v for k, v in (pdf.metadata or {}).items()
                      if k in ("Title", "Subject", "Author", "Keywords") and v}
        for page in pdf.pages:
            watermark_chars += [c["text"] for c in page.chars if _rotated(c)]
            upright = page.filter(lambda o: not _rotated(o))
            tables = [(t.bbox, t.extract()) for t in upright.find_tables()]
            lines = upright.extract_text_lines(return_chars=True, strip=True)
            raw_pages.append((page.page_number, page.height, lines, tables))
        page_count = len(pdf.pages)

    body = _body_size([p[2] for p in raw_pages])
    heading_sizes = sorted({_line_style(l["chars"])[0] for p in raw_pages for l in p[2]
                            if _line_style(l["chars"])[1] and _line_style(l["chars"])[0] > body + 0.5},
                           reverse=True)

    blocks, seen_title = [], False
    for page_no, height, lines, tables in raw_pages:
        items = []   # (top, block) so tables and lines interleave in reading order
        for bbox, rows in tables:
            for r, row in enumerate(rows):
                cells = [" ".join((c or "").split()) for c in row]
                if any(cells):
                    items.append((bbox[1] + r * 0.01, Block(kind="table_row", text=" | ".join(cells),
                                                            cells=cells, page=page_no)))

        def in_table(line):
            mid = (line["top"] + line["bottom"]) / 2
            return any(b[1] <= mid <= b[3] and b[0] - 1 <= line["x0"] <= b[2] + 1 for b, _ in tables)

        current, prev_bottom = None, None
        for line in lines:
            if in_table(line):
                current = None
                continue
            text = line["text"]
            size, bold, hidden = _line_style(line["chars"])
            if line["top"] > height - FOOTER_ZONE_PT:
                items.append((line["top"], Block(kind="footer", text=text, page=page_no, hidden=hidden)))
                current = None
                continue

            kind, level = "paragraph", 0
            if bold and size > body + 0.5:
                if not seen_title and size == heading_sizes[0] and (
                        size >= body * 1.6 or (page_no == 1 and not blocks and not items and not NUMBERED.match(text))):
                    kind = "title"                 # a large first line, or the unnumbered first line of the file
                else:
                    kind, level = "heading", _heading_level(text, size, heading_sizes, body)
            elif bold and size >= body - 0.5 and NUMBERED.match(text) and len(text) <= 90 and not text.endswith("."):
                kind, level = "heading", _heading_level(text, size, heading_sizes, body)   # "2.1 Scope" at body size
            elif text.startswith("•"):
                kind = "list_item"

            gap = (line["top"] - prev_bottom) if prev_bottom is not None else 99
            prev_bottom = line["bottom"]
            last = items[-1][1] if items else None
            if (kind in ("title", "heading") and last is not None and last.kind in ("title", "heading")
                    and gap < PARAGRAPH_GAP_PT and last.page == page_no and getattr(last, "_size", None) == size):
                last.text += " " + text          # a title or heading that wraps onto a second line
                continue
            continues = (current is not None and kind == "paragraph" and current.kind in ("paragraph", "list_item")
                         and gap < PARAGRAPH_GAP_PT and current.hidden == hidden)
            if continues:
                current.text += " " + text
                if hidden:
                    current.hidden_text += " " + text
                continue
            if kind == "title":
                seen_title = True
            block = Block(kind=kind, text=text.lstrip("• ").strip() if kind == "list_item" else text,
                          level=level, page=page_no, hidden=hidden, hidden_text=text if hidden else "")
            block._size = size
            items.append((line["top"], block))
            current = block if kind in ("paragraph", "list_item") else None

        blocks += [b for _, b in sorted(items, key=lambda x: x[0])]

    # Lines above the title (company letterhead, draft banners) are not body content.
    if seen_title:
        for b in blocks:
            if b.kind == "title":
                break
            if b.kind in ("paragraph", "heading"):
                b.kind, b.level = "letterhead", 0

    watermark = "".join(watermark_chars).strip()
    if watermark:
        warnings.append(f"Rotated watermark text found: '{watermark[:60]}'")
    if not any(b.kind == "heading" for b in blocks):
        warnings.append("No headings detected; sections are identified by paragraph number.")
    if not blocks:
        warnings.append("No extractable text (the PDF may be a scanned image).")
    return ParsedDocument(format="pdf", blocks=blocks, pages=page_count, properties=properties,
                          warnings=warnings, watermark=watermark)
