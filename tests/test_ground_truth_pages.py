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
    assert b"Pretended to be a manager or the CEO" in page and b"Blocked: kept away from the AI" in page


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


def test_confirming_a_requirement_says_the_matrix_needs_no_rebuild(loaded):
    with loaded.app_context():
        req = db.session.scalar(select(Requirement).where(Requirement.text.like("%paper copies are prohibited%")))
        pk = req.id
        same = {"req_type": req.req_type, "roles": req.roles, "due_stage": req.due_stage, "priority": req.priority,
                "competency": req.competency, "reason": "Checked against the source"}
    client = loaded.test_client()
    login(client, "training@aurelle.example")
    page = client.post(f"/requirements/{pk}", data={**same, "decision": "confirmed"}, follow_redirects=True).get_data(as_text=True)
    assert "does not need a new list" in page
    page = client.post(f"/requirements/{pk}", data={**same, "decision": "rejected"}, follow_redirects=True).get_data(as_text=True)
    assert "Build a new list on Who learns what" in page
    page = client.post(f"/requirements/{pk}", data={**same, "decision": "confirmed"}, follow_redirects=True).get_data(as_text=True)
    assert "Build a new list on Who learns what" in page                 # back from rejected: the matrix must include it again


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


def test_who_learns_what_shows_a_clickable_grid(loaded):
    import re
    client = loaded.test_client()
    login(client, "training@aurelle.example")
    assert "No list yet" in client.get("/matrix").get_data(as_text=True)
    client.post("/matrix/build")
    with loaded.app_context():
        number = db.session.scalar(select(MatrixVersion.version_no).order_by(MatrixVersion.version_no.desc()))
    index = client.get("/matrix").get_data(as_text=True)
    assert "Nothing is approved yet" in index and 'class="heat"' in index
    cells = re.findall(r'<a class="heat__cell heat--(\d) [^"]*"\s+href="([^"]+)"', index)
    assert cells and all(1 <= int(level) <= 5 for level, _ in cells)
    assert any(level == "5" for level, _ in cells)                        # the busiest square is darkest
    href = cells[0][1].replace("&amp;", "&")
    topic = re.search(r"topic=([^&#]+)", href).group(1)
    page = client.get(href.split("#")[0]).get_data(as_text=True)
    assert "when to learn what" in page and page.count('class="stagestrip__n"') == 6
    assert "Topic: <b>" in page                                           # rows narrowed to the clicked square
    shown = re.findall(r'<td class="small">([^<]+)</td>\s*<td><span class="rulelist__kind', page)
    from urllib.parse import unquote_plus
    assert shown and set(shown) == {unquote_plus(topic)}
    client.post(f"/matrix/{number}/approve")
    assert f"The approved list is version {number}" in client.get("/matrix").get_data(as_text=True)


def test_rules_page_filters_by_topic_and_speaks_plainly(loaded):
    import re
    client = loaded.test_client()
    login(client, "training@aurelle.example")
    page = client.get("/requirements").get_data(as_text=True)
    chips = re.findall(r'<a class="topicchip "[^>]*>([^<]+)<b>(\d+)</b>', page)
    assert chips and 'class="rulecard"' in page and "Not checked yet" in page
    topic, n = chips[0]
    narrowed = client.get("/requirements", query_string={"topic": topic}).get_data(as_text=True)
    assert f"{n} rule" in narrowed and narrowed.count('class="rulecard"') == min(int(n), 50)


def test_a_rule_page_leads_with_the_rule_itself(loaded):
    client = loaded.test_client()
    login(client, "training@aurelle.example")
    with loaded.app_context():
        req = db.session.scalar(select(Requirement).where(Requirement.text.like("%paper copies are prohibited%")))
        pk, text = req.id, req.text
    page = client.get(f"/requirements/{pk}").get_data(as_text=True)
    assert f'<h1 class="rulehead__text">{text}</h1>' in page.replace("&#39;", "'")
    assert "Who must learn it" in page and "Due by" in page and '<details class="expert">' in page


def test_a_document_added_after_the_list_asks_for_a_new_list(loaded):
    from src.services.ingestion import ingest_document
    client = loaded.test_client()
    login(client, "training@aurelle.example")
    client.post("/matrix/build")
    assert "arrived after this list was built" not in client.get("/matrix").get_data(as_text=True)
    with loaded.app_context():
        name = "HSP-01_v2.0.docx"
        assert ingest_document((SAMPLES / name).read_bytes(), name, today=TODAY).ok
    page = client.get("/matrix").get_data(as_text=True)
    assert "1 document arrived after this list was built" in page and "Build a new list now" in page


def test_changed_values_are_kept_even_if_the_decision_was_left_on_confirm(loaded):
    with loaded.app_context():
        req = db.session.scalar(select(Requirement).where(Requirement.text.like("%paper copies are prohibited%")))
        pk = req.id
        form = {"req_type": req.req_type, "roles": ["FOA"], "due_stage": req.due_stage, "priority": req.priority,
                "competency": req.competency, "decision": "confirmed", "reason": "Only the front desk scans passports"}
    client = loaded.test_client()
    login(client, "training@aurelle.example")
    page = client.post(f"/requirements/{pk}", data=form, follow_redirects=True).get_data(as_text=True)
    assert "Your changes are saved" in page
    with loaded.app_context():
        req = db.session.get(Requirement, pk)
        assert req.roles == ["FOA"] and req.review_status == "edited"
