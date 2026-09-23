"""Role Requirement Matrix build/approve, conditions and role mapping."""
from types import SimpleNamespace

from sqlalchemy import select

from database.models import JobRole, MatrixRow, MatrixVersion, Requirement
from role_matrix.applicability import resolve_roles
from role_matrix.conditions import applies


def test_matrix_draft_and_approval(corpus):
    session, _ = corpus
    from src.services.matrix import approve, build_draft
    actor = {"email": "training@aurelle.example", "app_role": "training_manager"}
    draft = build_draft(actor)
    assert draft.status == "draft"
    assert draft.stats["requirements"] >= 150 and draft.stats["mandatory_requirements"] >= 50
    assert set(draft.stats["per_role"]) == {"FOA", "GRE", "HKS", "FBA", "MTT", "SEE", "RVA", "FNA", "HRE", "DMG"}
    # only active (or expired) sources: no superseded, draft or scheduled versions in the matrix
    versions = {v for _, v in draft.source_documents}
    assert ("3.0-DRAFT" not in versions)
    assert not any(d == "LVP-01" and v == "1.0" for d, v in draft.source_documents)
    approve(draft.version_no, actor)
    assert session.scalar(select(MatrixVersion.status).where(MatrixVersion.version_no == draft.version_no)) == "approved"


def test_quarantined_and_external_content_never_reaches_the_matrix(corpus):
    session, _ = corpus
    texts = [r.text for r in session.scalars(select(Requirement).join(MatrixRow, MatrixRow.requirement_id == Requirement.id))]
    assert not any("Horizon" in t for t in texts)                 # external partner pack: tier 0
    assert not any("skip quizzes" in t for t in texts)            # quarantined fake-authority paragraph


def test_new_role_picks_up_existing_requirements(corpus):
    session, _ = corpus
    roles = session.scalars(select(JobRole)).all() + [SimpleNamespace(code="NAU", name="Night Auditor",
                                                                      aliases=["auditor", "night auditor"],
                                                                      department="Front Office")]
    req = session.scalar(select(Requirement).where(Requirement.text.like("Before running the day-end, the auditor%")))
    assert "NAU" in resolve_roles(req.subject, req.chunk.heading_path, req.document.applies_to_text, roles)


def employee(country="UAE", ptype="Hotel", ird=True, assignments=(), certs=(), years=0, shift="day"):
    return {"property": {"country": country, "type": ptype, "services": {"in_room_dining": ird}},
            "assignments": list(assignments), "certifications": list(certs), "experience_years": years,
            "shift_pattern": shift}


def test_conditions_distinguish_employees_in_the_same_role():
    ird = {"field": "assignments", "op": "contains", "value": "in_room_dining"}
    grace = employee("Malaysia", ird=True, assignments=["in_room_dining"])     # Penang, assigned to IRD
    farah = employee("Oman", ird=False)                                        # Muscat Bay: no IRD service
    assert applies(ird, grace) is True and applies(ird, farah) is False
    assert applies({"field": "property.country", "op": "eq", "value": "Malaysia"}, grace) is True
    assert applies({"field": "experience_years", "op": "gte", "value": 2}, employee(years=3)) is True
    assert applies({"field": "shift_pattern", "op": "in", "value": ["night", "rotating"]}, employee()) is False
    assert applies(None, farah) is True
