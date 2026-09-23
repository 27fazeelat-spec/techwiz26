"""End-to-end ingestion of the full sample collection, checked against the dataset registers."""
import io

from sqlalchemy import select

from database.models import AuditLog, Chunk, Document
from document_processing.models import normalise_text
from src.services.ingestion import ingest_document

from tests.conftest import SAMPLES, TODAY, read_register


def get_doc(session, doc_id, version):
    return session.scalar(select(Document).where(Document.doc_id == doc_id, Document.version == version))


def test_every_sample_document_is_ingested(corpus):
    _, results = corpus
    failures = {name: r.errors for name, r in results.items() if not r.ok}
    assert not failures


def test_document_statuses_match_the_register(corpus):
    session, _ = corpus
    mismatches = []
    for row in read_register("02_Document_Register.csv"):
        doc = get_doc(session, row["doc_id"], row["version"])
        if doc is None or doc.status != row["status"].lower():
            mismatches.append((row["doc_id"], row["version"], row["status"], doc and doc.status))
    assert not mismatches


def test_header_metadata_is_read_from_the_document(corpus):
    session, _ = corpus
    for row in read_register("02_Document_Register.csv"):
        if row["metadata_header"] != "Y":
            continue
        doc = get_doc(session, row["doc_id"], row["version"])
        assert doc.metadata_source["doc_id"] == "header"
        if row["effective_date"]:
            assert doc.effective_date.isoformat() == row["effective_date"]


def test_every_requirement_is_traceable_to_a_chunk(corpus):
    """SRS Steps 6-7: each register clause sits in a chunk with the right document version and section."""
    session, _ = corpus
    register_version = {}
    for row in read_register("02_Document_Register.csv"):
        if row["status"] in ("Active", "Expired"):
            register_version.setdefault(row["doc_id"], row["version"])
    missing = []
    for req in read_register("03_Requirements_Register.csv"):
        version = register_version[req["doc_id"]]
        chunks = session.scalars(select(Chunk).where(Chunk.doc_id == req["doc_id"], Chunk.version == version,
                                                     Chunk.section_id == req["section"])).all()
        clause = normalise_text(req["clause_text"])
        if not any(clause in normalise_text(c.text) for c in chunks):
            missing.append(f"{req['req_id']} ({req['doc_id']} v{version} §{req['section']})")
    assert not missing, f"{len(missing)} requirement(s) not traceable: {missing[:10]}"


def test_hidden_content_is_flagged_on_chunks(corpus):
    session, _ = corpus
    hidden = {(c.doc_id, c.section_id) for c in session.scalars(select(Chunk).where(Chunk.hidden_content))}
    assert ("ROL-03", "3.2") in hidden
    assert ("PTR-01", "Appendix") in hidden
    footer = session.scalar(select(Chunk).where(Chunk.doc_id == "SOP-HK-02", Chunk.section_id == "footer"))
    assert footer and footer.text.startswith("SYSTEM:")


def test_only_active_versions_are_marked_as_sources(corpus):
    session, _ = corpus
    statuses = set(session.scalars(select(Chunk.doc_status).distinct()))
    assert statuses == {"active", "superseded", "scheduled", "expired", "draft"}
    assert not session.scalars(select(Chunk).where(Chunk.doc_id == "LVP-01", Chunk.version == "1.0",
                                                   Chunk.doc_status == "active")).first()


def test_duplicate_file_is_rejected(corpus):
    data = (SAMPLES / "HRP-01_v2.1.docx").read_bytes()
    result = ingest_document(data, "copy.docx", today=TODAY)
    assert not result.ok and "already stored as HRP-01 version 2.1" in result.errors[0]


def test_existing_version_number_with_different_content_is_rejected(corpus):
    from docx import Document as DocxDocument
    doc = DocxDocument(SAMPLES / "LVP-01_v1.0.docx")
    doc.add_paragraph("An unofficial edit that keeps the same version number.")
    buffer = io.BytesIO()
    doc.save(buffer)
    result = ingest_document(buffer.getvalue(), "edited.docx", today=TODAY)
    assert not result.ok and "LVP-01 version 1.0 already exists" in result.errors[0]


def test_document_without_header_uses_form_and_inferred_values(corpus):
    session, _ = corpus
    memo = session.scalar(select(Document).where(Document.doc_id == "MEM-01"))
    assert memo.metadata_source["category"] == "form"
    assert memo.metadata_source["version"] == "heuristic"
    assert memo.status == "active"


def test_audit_log_is_append_only(corpus):
    session, _ = corpus
    entry = session.scalars(select(AuditLog)).first()
    entry.reason = "tampered"
    try:
        session.flush()
        raise AssertionError("audit entry was updated")
    except PermissionError:
        session.rollback()


def test_ingest_folder_writes_a_readiness_report(app, tmp_path):
    import shutil
    from tests.conftest import SAMPLES
    folder = tmp_path / "unseen"
    folder.mkdir()
    for name in ("GDP-01_v1.0.docx", "MEM-01_v1.0.docx"):
        if (SAMPLES / name).exists():
            shutil.copy(SAMPLES / name, folder / name)
    (folder / "broken.pdf").write_bytes(b"not a pdf at all")
    report = tmp_path / "readiness.md"
    result = app.test_cli_runner().invoke(args=["ingest-folder", str(folder), "--report", str(report)])
    assert result.exit_code == 0, result.output
    text = report.read_text(encoding="utf-8")
    assert "| broken.pdf | **rejected** |" in text and "ingested" in text
