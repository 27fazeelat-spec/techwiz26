"""Staff workspace: the admin home, the Terracotta theme switch and the Ctrl+K search endpoint."""
from flask import current_app

from tests.conftest import login


def test_admin_home_shows_the_pipeline_and_the_theme(corpus):
    client = current_app.test_client()
    login(client, "admin@aurelle.example")
    html = client.get("/dashboard/admin").get_data(as_text=True)
    assert "theme-terra" in html and "css/terra.css" in html and "js/workspace.js" in html
    assert "From policy to plan" in html and "Needs you" in html
    assert "data-cmdk-open" in html


def test_other_roles_keep_their_theme_until_moved(corpus):
    client = current_app.test_client()
    login(client, "leila.haddad@aurelle.example")
    html = client.get("/dashboard/me").get_data(as_text=True)
    assert "theme-terra" not in html and "css/terra.css" not in html


def test_search_finds_documents_and_requirements_for_staff(corpus):
    client = current_app.test_client()
    login(client, "admin@aurelle.example")
    data = client.get("/api/search?q=GDP").get_json()
    labels = {g["label"]: g["items"] for g in data["groups"]}
    assert labels["Documents"] and labels["Documents"][0]["code"].startswith("GDP-01")
    assert all(i["code"].startswith("R-GDP") or "GDP" in i["title"] for i in labels.get("Requirements", []))
    assert client.get("/api/search?q=a").get_json() == {"groups": []}          # too short to search


def test_search_respects_permissions(corpus):
    client = current_app.test_client()
    login(client, "leila.haddad@aurelle.example")                              # employees cannot browse policies
    data = client.get("/api/search?q=GDP").get_json()
    assert data == {"groups": []}


def test_training_manager_gets_the_theme_but_not_other_peoples_decisions(corpus):
    from sqlalchemy import select
    from database import db
    from database.models import Conflict
    from src.services import progress
    from tests.test_planning_pipeline import leila
    from tests.test_progress import assigned, rows
    assigned()
    plan = progress.assigned_plan(leila())                                     # the plan the team page shows
    task = next(r for r in rows(plan) if r.plan_item.item_type == "assessment")
    task.status, task.score, task.verified_by = "not_started", None, None      # an assessment still to be marked
    db.session.commit()
    client = current_app.test_client()
    login(client, "training@aurelle.example")
    home = client.get("/dashboard/plans").get_data(as_text=True)
    assert "theme-terra" in home and "Plans board" in home
    page = client.get("/team/E001").get_data(as_text=True)
    assert "Waiting for Omar Siddiqui" in page and 'value="approve"' not in page           # sign-off is the line manager's job
    assert client.post(f"/team/progress/{task.id}/signoff", data={"decision": "approve", "score": "90"}).status_code == 403
    conflict = db.session.scalar(select(Conflict).limit(1))
    if conflict:                                                               # conflicts are the reviewer's decision
        assert client.post(f"/conflicts/{conflict.id}/resolve", data={}).status_code == 403
    assert client.get("/conflicts").status_code == 200                        # but the trainer may read them
    client.post("/logout")
    login(client, "omar.siddiqui@aurelle.example")                            # Leila's manager
    assert 'value="approve"' in client.get("/team/E001").get_data(as_text=True)


def test_reviewer_decides_conflicts_but_does_not_rerun_detection(corpus):
    client = current_app.test_client()
    login(client, "evaluator@aurelle.example")
    home = client.get("/dashboard/review").get_data(as_text=True)
    assert "theme-terra" in home and "What is waiting" in home
    page = client.get("/conflicts").get_data(as_text=True)
    assert "Run contradiction check" not in page                              # detection is the administrator's job
    assert client.post("/conflicts/detect").status_code == 403
    client.post("/logout")
    login(client, "admin@aurelle.example")
    assert "Run contradiction check" in client.get("/conflicts").get_data(as_text=True)


def test_line_manager_panel_and_team_search(corpus):
    client = current_app.test_client()
    login(client, "omar.siddiqui@aurelle.example")
    home = client.get("/dashboard/team").get_data(as_text=True)
    assert "theme-terra" in home and "Waiting for your sign-off" in home and 'href="#"' not in home
    data = client.get("/api/search?q=Leila").get_json()
    assert data["groups"][0]["label"] == "My team" and data["groups"][0]["items"][0]["code"] == "E001"
    assert client.get("/api/search?q=GDP").get_json() == {"groups": []}      # no policy browsing for managers
