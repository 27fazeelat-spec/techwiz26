"""Contradiction detection and precedence (documentation/dataset/04_Test_Cases.md section 1)."""
from sqlalchemy import select

from contradiction_checks import detect, resolve
from database import db
from database.models import AuditLog, Conflict, JobRole, MatrixRow, Requirement
from python_validation import validate
from python_validation.statuses import plan_status
from tests.conftest import login
from tests.test_validation_rules import GOOD_ITEMS, ctx, req

# case: ({(doc, section), (doc, section)}, winning doc or None for manual review, rule)
PLANNED = {
    "C01": ({("REV-01", "3.4"), ("FAQ-01", "Q12")}, "REV-01", "tier"),
    "C02": ({("SOP-FO-01", "5.2"), ("ROL-01", "3.3")}, "SOP-FO-01", "tier"),
    "C03": ({("LVP-01", "2.4"), ("FAQ-01", "Q4")}, "LVP-01", "tier"),
    "C05": ({("GDP-01", "4.5"), ("MEM-01", "para 2")}, "GDP-01", "tier"),
    "C06": ({("FLS-01", "3.1"), ("HBK-01", "6.1")}, "FLS-01", "tier"),
    "C07": ({("SOP-EN-01", "2.3"), ("ROL-02", "1.3")}, "SOP-EN-01", "tier"),
    "C08": ({("FSA-01", "2.1"), ("HBK-01", "5.3")}, "FSA-01", "tier"),
    "C09": ({("SAL-01", "4.1"), ("FIN-01", "5.2")}, None, "same_tier_manual"),
    "C10": ({("ISP-01", "3.1"), ("ITA-01", "3.1")}, "ISP-01", "tier"),
    "C11": ({("ESC-01", "2.1"), ("HSP-01", "2.1")}, "ESC-01", "life_safety"),
    "C12": ({("HSP-01", "5.2"), ("FAQ-01", "Q20")}, "HSP-01", "tier"),
    "C13": ({("COC-01", "3.2"), ("HBK-01", "7.2")}, "COC-01", "tier"),
}


def stored_conflicts():
    from src.services.conflicts import detect_and_store
    detect_and_store()
    db.session.commit()
    return db.session.scalars(select(Conflict).where(Conflict.kind == "cross_document")).all()


def test_every_planned_conflict_is_found_and_resolved_as_documented(corpus):
    found = {frozenset({(c.left.doc_id, c.left.section_id), (c.right.doc_id, c.right.section_id)}): c
             for c in stored_conflicts()}
    problems = []
    for case, (pair, winner, rule) in PLANNED.items():
        c = found.get(frozenset(pair))
        if c is None:
            problems.append(f"{case} not detected")
        elif c.rule_applied != rule or (c.winner.doc_id if c.winner else None) != winner:
            problems.append(f"{case}: rule {c.rule_applied}, winner {c.winner.doc_id if c.winner else None}")
    assert not problems


def test_few_unplanned_conflicts(corpus):
    planned = {frozenset(p) for p, _, _ in PLANNED.values()}
    extra = [c for c in stored_conflicts()
             if frozenset({(c.left.doc_id, c.left.section_id), (c.right.doc_id, c.right.section_id)}) not in planned]
    assert len(extra) <= 3          # today: 2, both genuine (breach 1 hour vs immediately; FAQ vs SOP waiver)


def test_version_changes_are_recorded(corpus):
    stored_conflicts()
    versions = db.session.scalars(select(Conflict).where(Conflict.kind == "version")).all()
    assert len(versions) >= 8 and all(c.rule_applied == "same_lineage" for c in versions)


def test_overridden_clauses_leave_the_matrix_and_the_sources(corpus):
    from genai_pipeline.retrieval import build_bundle
    from src.services.matrix import build_draft
    version = build_draft({"email": "test"})
    annual = db.session.scalar(select(Requirement).where(Requirement.text.like("%annual fire drill%"),
                                                         Requirement.version == "3.0"))
    assert not db.session.scalar(select(MatrixRow).where(MatrixRow.matrix_version_id == version.id,
                                                         MatrixRow.requirement_id == annual.id))
    assert version.stats["excluded_by_precedence"] >= 10
    foa = db.session.scalar(select(JobRole).where(JobRole.code == "FOA"))
    assert "annual fire drill" not in build_bundle(foa).text
    assert "every six months" in build_bundle(foa).text


def test_plan_following_an_overridden_rule_is_contradictory():
    c = ctx([req("R-A-01-001")], GOOD_ITEMS)
    c.conflicts = {"R-A-01-001": {"type": "lost", "winner": "R-X-01-001", "conflict": "CF-0001",
                                  "explanation": "X outranks A", "rule": "tier"}}
    findings, _ = validate(c)
    assert plan_status(findings) == "Contradictory"


def test_detector_unit_behaviour():
    base = {"tier": 1, "category": "Policy", "version": "1.0", "section_id": "1"}
    a = {**base, "id": 1, "req_id": "R-A", "doc_id": "A-01", "strength": "mandatory",
         "text": "Chilled food must be stored at or below 4 °C."}
    b = {**base, "id": 2, "req_id": "R-B", "doc_id": "B-01", "tier": 4, "strength": "mandatory",
         "text": "Chilled food must be kept at or below 5 °C."}
    c = {**base, "id": 3, "req_id": "R-C", "doc_id": "C-01", "strength": "mandatory",
         "text": "Passwords must be changed every 90 days."}
    conflicts = detect([a, b, c])
    assert len(conflicts) == 1 and conflicts[0]["differences"][0]["type"] == "number"
    assert resolve(conflicts[0])["rule"] == "tier"


def test_reviewer_decides_a_same_tier_conflict_and_the_decision_survives(app):
    from src.services.ingestion import ingest_document
    from tests.conftest import SAMPLES, TODAY
    with app.app_context():
        for name in ("SAL-01_v1.1.docx", "FIN-01_v2.0.pdf"):
            assert ingest_document((SAMPLES / name).read_bytes(), name, today=TODAY).ok
        manual = [c for c in stored_conflicts() if c.status == "manual_review"]
        assert manual
        pk, code = manual[0].id, manual[0].conflict_code
    client = app.test_client()
    login(client, "evaluator@aurelle.example")
    assert client.post(f"/conflicts/{pk}/resolve", data={"winner": "left"}).status_code == 302   # no reason: refused
    with app.app_context():
        assert db.session.get(Conflict, pk).status == "manual_review"
    client.post(f"/conflicts/{pk}/resolve", data={"winner": "right", "reason": "Finance policy applies group-wide"})
    with app.app_context():
        conflict = db.session.get(Conflict, pk)
        assert conflict.status == "resolved_by_reviewer" and conflict.review_reason
        assert db.session.scalar(select(AuditLog).where(AuditLog.action == "conflict.resolved", AuditLog.entity_id == code))
        stored_conflicts()                       # re-detection keeps the reviewer's decision
        assert db.session.get(Conflict, pk).status == "resolved_by_reviewer"
    assert client.get("/conflicts").status_code == 200
