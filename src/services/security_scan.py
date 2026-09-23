"""Apply the injection scanner to a stored document version: record findings, quarantine chunks."""
from database import db
from database.models import SecurityFinding
from security import scan_document


def scan_and_record(doc):
    """Scan doc.chunks; returns the list of SecurityFinding rows added to the session."""
    chunk_by_id = {c.chunk_id: c for c in doc.chunks}
    result = scan_document(
        [{"chunk_id": c.chunk_id, "text": c.text, "raw_text": c.raw_text, "hidden_text": c.hidden_text}
         for c in doc.chunks],
        is_draft=doc.is_draft, watermark=(doc.parse or {}).get("watermark") or "")
    rows = []
    for f in result.findings:
        chunk = chunk_by_id.get(f.chunk_id)
        rows.append(SecurityFinding(document=doc, chunk=chunk, technique=f.technique, pattern=f.pattern[:300],
                                    severity=f.severity, action=f.action, excerpt=f.excerpt, decoded=f.decoded))
    for chunk_id in result.quarantined:
        chunk_by_id[chunk_id].quarantined = True
    db.session.add_all(rows)
    return rows


def flag_irrelevant(doc, requirement_count):
    """A source document (tier > 0) that yields no requirements at all is probably mis-filed or irrelevant."""
    if doc.tier > 0 and not doc.is_draft and requirement_count == 0:
        row = SecurityFinding(document=doc, technique="irrelevant", pattern="no-requirements", severity="low",
                              action="flag", excerpt=f"'{doc.title}' is filed as {doc.category} but contains no "
                                                     "obligations, recommendations or permissions.")
        db.session.add(row)
        return row
    return None
