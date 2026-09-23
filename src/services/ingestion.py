"""Pipeline A - document ingestion (documentation/02_Architecture.md section 4).

Validate -> parse -> metadata -> validate metadata -> store -> chunk -> security scan ->
requirement extraction -> resolve versions -> audit. Conflict detection plugs in after extraction.
The whole ingestion commits as one transaction, so a failure never leaves a half-stored document.
"""
from dataclasses import dataclass, field

from sqlalchemy import select

from config.loader import load_config
from database import audit, db
from database.models import Chunk, Document, DocumentFile
from document_processing import parse_document
from document_processing.chunker import chunk_document
from document_processing.metadata import extract_metadata
from document_processing.versioning import compute_statuses
from document_validation import check_file, sha256, validate_metadata
from src.services.requirements import extract_document_requirements
from src.services.security_scan import flag_irrelevant, scan_and_record


@dataclass
class IngestResult:
    ok: bool = False
    doc: Document | None = None
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    lineage_changes: dict = field(default_factory=dict)

    def step(self, name, status, detail=""):
        self.steps.append({"name": name, "status": status, "detail": detail})

    def fail(self, name, errors):
        self.errors += errors
        self.step(name, "failed", "; ".join(errors))
        return self


def ingest_document(data, filename, form=None, actor=None, today=None):
    rules = load_config("documents")
    tiers = load_config("precedence")["tiers"]
    result = IngestResult()

    # 1. File checks
    fmt, errors, warnings = check_file(data, filename, rules["limits"]["max_upload_mb"],
                                       rules["limits"]["allowed_formats"])
    result.warnings += warnings
    if errors:
        return result.fail("File check", errors)
    digest = sha256(data)
    duplicate = db.session.execute(
        select(Document.doc_id, Document.version).join(DocumentFile).where(DocumentFile.sha256 == digest)).first()
    if duplicate:
        return result.fail("File check", [f"This exact file is already stored as {duplicate.doc_id} "
                                          f"version {duplicate.version}."])
    result.step("File check", "passed", f"{fmt.upper()}, {len(data) / 1024:.0f} KB")

    # 2. Parse
    try:
        parsed = parse_document(data, fmt)
    except Exception as exc:  # corrupt or password-protected files
        return result.fail("Parse", [f"The file could not be read ({type(exc).__name__}). "
                                     "Check that it opens normally and is not password-protected."])
    words = parsed.word_count()
    if words < rules["limits"]["min_words"]:
        return result.fail("Parse", [f"The document contains almost no readable text ({words} words). "
                                     "Scanned image PDFs are not supported."])
    result.warnings += parsed.warnings
    result.step("Parse", "passed", f"{len(parsed.blocks)} blocks, {words} words"
                + (f", {parsed.pages} pages" if parsed.pages else ""))

    # 3. Metadata
    meta, sources, warnings, consumed = extract_metadata(
        parsed, filename, form, rules.get("category_synonyms"), rules.get("draft_markers", []))
    result.warnings += warnings
    existing = db.session.scalars(select(Document.version).where(Document.doc_id == meta.get("doc_id"))).all()
    errors, warnings = validate_metadata(meta, rules["categories"], rules["departments"], existing)
    result.warnings += warnings
    if errors:
        return result.fail("Metadata", errors)
    result.step("Metadata", "passed", f"{meta['doc_id']} v{meta['version']} ({meta['category']})")

    # 4. File and document record
    try:
        file = DocumentFile(filename=filename, sha256=digest, size_bytes=len(data), format=fmt, content=data)
        doc = Document(
            doc_id=meta["doc_id"], version=meta["version"], title=meta.get("title"), category=meta["category"],
            tier=tiers.get(meta["category"], 0), owner_department=meta.get("owner_department"),
            applies_to_text=meta.get("applies_to"), header_status=meta.get("status"), is_draft=meta["is_draft"],
            effective_date=meta.get("effective_date"), expiry_date=meta.get("expiry_date"),
            supersedes_text=meta.get("supersedes"), status="pending", file=file, metadata_source=sources,
            parse={"pages": parsed.pages, "blocks": len(parsed.blocks), "words": words,
                   "headings": sum(b.kind == "heading" for b in parsed.blocks),
                   "table_rows": sum(b.kind == "table_row" for b in parsed.blocks),
                   "hidden_blocks": sum(b.hidden for b in parsed.blocks),
                   "watermark": parsed.watermark or None, "properties": parsed.properties, "scanned": True},
            warnings=result.warnings, uploaded_by=(actor or {}).get("email", "system"))
        db.session.add(doc)
        result.step("Store", "passed", "Original file saved")

        # 5. Chunks
        chunks = chunk_document(parsed, doc.doc_id, doc.version, exclude=consumed,
                                max_words=rules["chunking"]["max_words"])
        for c in chunks:
            c["position"] = c.pop("order")
            doc.chunks.append(Chunk(**c))
        doc.chunk_count = len(chunks)
        db.session.flush()
        result.step("Chunk", "passed", f"{len(chunks)} traceable chunks")

        # 6. Security scan: quarantine visible attacks, exclude hidden text
        findings = scan_and_record(doc)
        quarantined = sum(c.quarantined for c in doc.chunks)
        result.step("Security scan", "flagged" if findings else "passed",
                    f"{len(findings)} finding(s), {quarantined} chunk(s) quarantined" if findings else "No suspicious content")
        db.session.flush()

        # 7. Requirement extraction (deterministic, no GenAI)
        requirements = extract_document_requirements(doc)
        if flag_irrelevant(doc, len(requirements)):
            result.warnings.append("The document is filed as a source but contains no requirements.")
        result.step("Requirements", "passed" if doc.tier else "skipped",
                    f"{len(requirements)} requirement(s) extracted" if doc.tier else
                    "Not an authoritative source; no requirements extracted")

        # 8. Versions
        result.lineage_changes = refresh_lineage(doc.doc_id, today)
        result.step("Versions", "passed", f"This version is {doc.status}")
        if doc.tier:
            from src.services.changes import detect_changes
            changes = detect_changes(doc.doc_id, actor)
            if changes:
                result.step("Policy change", "flagged", f"{sum(c.counts.get(k, 0) for c in changes for k in ('changed', 'added', 'removed'))} "
                                                        f"clause(s) differ from the previous version; see Policy changes")

        audit.record("document.ingested", "document", doc.doc_id, actor=actor, version=doc.version,
                     after={"status": doc.status, "chunks": len(chunks), "requirements": len(requirements),
                            "security_findings": len(findings)},
                     detail={"warnings": len(result.warnings), "lineage": result.lineage_changes}, commit=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    result.ok, result.doc = True, doc
    return result


def refresh_lineage(doc_id, today, commit=False):
    """Recompute statuses for every version of a document. Returns what changed."""
    versions = db.session.scalars(select(Document).where(Document.doc_id == doc_id)).all()
    computed = compute_statuses([{
        "version": v.version, "is_draft": v.is_draft,
        "effective_date": v.effective_date, "expiry_date": v.expiry_date,
    } for v in versions], today)

    changes = {}
    for v in versions:
        status, superseded_by = computed[v.version]
        if v.status != status:
            changes[v.version] = {"from": v.status, "to": status}
        v.status, v.superseded_by = status, superseded_by
        db.session.query(Chunk).filter_by(document_id=v.id).update({"doc_status": status})
    if commit:
        db.session.commit()
    return changes
