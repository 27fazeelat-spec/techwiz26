"""Policy update -> impact analysis -> selective regeneration (SRS Steps 57-59, integrity challenge 4)."""
import pytest
from sqlalchemy import select

from database import db
from database.models import AuditLog, ChangeImpact, Employee, PlanItemRequirement, Requirement
from src.services import changes
from src.services.planning import generate_plan
from tests.conftest import SAMPLES, TODAY, login
from tests.fakes import ScriptedProvider

CONFIG = {"GEMINI_API_KEY": "test", "GEMINI_MODEL": ""}
ACTOR = {"email": "training@aurelle.example", "app_role": "training_manager"}
LATER = "GDP-01_v2.0.docx"


def ingest(names):
    from src.cli import _manifest
    from src.services.ingestion import ingest_document
    manifest = _manifest(SAMPLES)
    for name in names:
        assert ingest_document((SAMPLES / name).read_bytes(), name, form=manifest.get(name), actor=ACTOR, today=TODAY).ok


def approved_matrix():
    from src.services.matrix import approve, build_draft
    return approve(build_draft(ACTOR).version_no, ACTOR)


@pytest.fixture()
def before_update(app):
    """Every sample document except GDP-01 v2.0, an approved matrix and a plan for Leila (FOA)."""
    with app.app_context():
        ingest(sorted(p.name for p in SAMPLES.iterdir() if p.suffix in (".pdf", ".docx") and p.name != LATER))
        approved_matrix()
        leila = db.session.scalar(select(Employee).where(Employee.employee_code == "E001"))
        plan = generate_plan(leila, {"email": "test"}, CONFIG, provider=ScriptedProvider(spread_categories=True))
        yield app, plan


def test_new_version_is_compared_clause_by_clause(before_update):
    app, plan = before_update
    ingest([LATER])
    change = db.session.scalar(select(ChangeImpact).where(ChangeImpact.doc_id == "GDP-01"))
    assert (change.from_version, change.to_version) == ("1.0", "2.0")
    assert change.counts.get("changed", 0) >= 1
    changed = next(x for x in change.changes if x["change"] == "changed")
    assert changed["old_text"] != changed["new_text"] and changed["req_id"].startswith("R-GDP-01-")
    assert db.session.scalar(select(AuditLog).where(AuditLog.action == "policy.change_detected", AuditLog.entity_id == "GDP-01"))
    assert changes.detect_changes("GDP-01") == []                           # idempotent


def test_impact_lists_items_plans_and_employees(before_update):
    app, plan = before_update
    ingest([LATER])
    change = db.session.scalar(select(ChangeImpact).where(ChangeImpact.doc_id == "GDP-01"))
    info = changes.impact(change)
    assert [p["plan"].id for p in info["plans"]] == [plan.id] and info["employees"] == 1
    touched = {x["req_id"] for x in change.changes if x["change"] in ("changed", "removed")}
    affected = {r for p in info["plans"] for m in p["modules"].values() for r in m["requirements"]}
    assert affected and affected <= touched
    assert info["items"] >= len(affected) and change.status == "open"


def test_regeneration_needs_an_updated_matrix_and_touches_only_affected_modules(before_update):
    app, plan = before_update
    ingest([LATER])
    change = db.session.scalar(select(ChangeImpact).where(ChangeImpact.doc_id == "GDP-01"))
    with pytest.raises(changes.ChangeError):                                # matrix still reflects v1.0
        changes.regenerate_for_change(change, ACTOR, CONFIG, provider=ScriptedProvider(spread_categories=True))
    approved_matrix()
    affected_modules = {k for p in changes.impact(change)["plans"] for k in p["modules"]}
    [(old, new)] = changes.regenerate_for_change(change, ACTOR, CONFIG, provider=ScriptedProvider(spread_categories=True))
    assert new.version == old.version + 1 and old.status == "superseded"
    detail = db.session.scalar(select(AuditLog).where(AuditLog.action == "plan.regenerated")
                               .order_by(AuditLog.id.desc())).detail
    assert set(detail["modules"]) >= affected_modules
    assert len(detail["modules"]) < len(old.modules)                       # not a full regeneration
    assert change.status == "regenerated" and change.regenerated[0]["to_version"] == new.version
    # every link in the new version points at a current clause, so the next update is traced correctly
    v1_rows = set(db.session.scalars(select(Requirement.id).where(Requirement.document_id == change.from_document_id)))
    links = {l.requirement_id for m in new.modules for i in m.items for l in i.requirement_links}
    assert not (links & v1_rows)
    assert changes.impact(change)["plans"] == []


def test_policy_change_pages(before_update):
    app, plan = before_update
    ingest([LATER])
    change = db.session.scalar(select(ChangeImpact).where(ChangeImpact.doc_id == "GDP-01"))
    client = app.test_client()
    login(client, "training@aurelle.example")
    listing = client.get("/changes").get_data(as_text=True)
    card = listing[listing.index('class="chgcard'):]
    assert "GDP-01" in card[:card.index("</a>")] and "employee" in card[:card.index("</a>")]   # who it affects, on the card
    page = client.get(f"/changes/{change.id}").data
    assert b"<del>" in page or b"<ins>" in page
    assert b"Build and approve a new Role Requirement Matrix" in page
    client.post("/logout")
    login(client, "leila.haddad@aurelle.example")
    assert client.get("/changes").status_code == 403
