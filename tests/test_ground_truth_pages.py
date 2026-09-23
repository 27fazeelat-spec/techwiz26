"""Web pages for requirements, matrix and security: access control, audited edits, build and approve."""
import pytest
from sqlalchemy import select

from database import db
from database.models import AuditLog, MatrixVersion, Requirement
from tests.conftest import SAMPLES, TODAY, login


@pytest.fixture()
def loaded(app):
    """App with seed data and three documents ingested (one with a planted attack)."""
    from src.services.ingestion import ingest_document
    with app.app_context():
        for name in ("GDP-01_v2.0.docx", "MEM-01_v1.0.docx", "SOP-FO-01_v2.0.docx"):
            form = {"category": "Informal Guidance"} if name.startswith("MEM") else None
            assert ingest_document((SAMPLES / name).read_bytes(), name, form=form, today=TODAY).ok
    return app


def test_pages_render_for_training_manager(loaded):
    client = loaded.test_client()
    login(client, "training@aurelle.example")
    for url in ("/requirements", "/requirements?role=FOA&type=Must+Know", "/matrix", "/security", "/dashboard/admin"):
        assert client.get(url).status_code == 200, url
    page = client.get("/security").data
    assert b"Fake authority" in page and b"MEM-01" in page


def test_employee_cannot_see_ground_truth(loaded):
    client = loaded.test_client()
    login(client, "leila.haddad@aurelle.example")
    for url in ("/requirements", "/matrix", "/security"):
        assert client.get(url).status_code == 403


def test_requirement_edit_is_audited_and_reviewer_cannot_edit(loaded):
    with loaded.app_context():
        req = db.session.scalar(select(Requirement).where(Requirement.text.like("%paper copies are prohibited%")))
        pk, req_id = req.id, req.req_id
    reviewer = loaded.test_client()
    login(reviewer, "evaluator@aurelle.example")
    assert reviewer.get(f"/requirements/{pk}").status_code == 200
    form = {"req_type": "Must Know", "roles": ["FOA", "DMG"], "due_stage": "W1", "priority": "High",
            "competency": "Data Privacy", "decision": "edited", "reason": "Only passport-scanning roles"}
    assert reviewer.post(f"/requirements/{pk}", data=form).status_code == 403

    manager = loaded.test_client()
    login(manager, "training@aurelle.example")
    assert manager.post(f"/requirements/{pk}", data=form).status_code == 302
    with loaded.app_context():
        req = db.session.get(Requirement, pk)
        assert req.roles == ["FOA", "DMG"] and req.review_status == "edited"
        entry = db.session.scalar(select(AuditLog).where(AuditLog.action == "requirement.edited",
                                                         AuditLog.entity_id == req_id))
        assert entry.before["roles"] != entry.after["roles"] and entry.reason == "Only passport-scanning roles"


def test_matrix_build_and_approve_through_the_web(loaded):
    client = loaded.test_client()
    login(client, "training@aurelle.example")
    response = client.post("/matrix/build")
    assert response.status_code == 302
    with loaded.app_context():
        number = db.session.scalar(select(MatrixVersion.version_no).order_by(MatrixVersion.version_no.desc()))
    assert client.get(f"/matrix/{number}?role=FOA").status_code == 200
    assert client.post(f"/matrix/{number}/approve").status_code == 302
    with loaded.app_context():
        assert db.session.scalar(select(MatrixVersion.status).where(MatrixVersion.version_no == number)) == "approved"
