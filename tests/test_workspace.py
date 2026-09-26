"""Staff workspace: the admin home, the Terracotta theme switch and the Ctrl+K search endpoint."""
from flask import current_app

from tests.conftest import login


def test_admin_home_shows_plain_charts_and_the_theme(corpus):
    client = current_app.test_client()
    login(client, "admin@aurelle.example")
    html = client.get("/dashboard/admin").get_data(as_text=True)
    assert "theme-terra" in html and "css/terra.css" in html and "js/workspace.js" in html
    assert "Needs you" in html and "Training progress" in html and "Progress by department" in html
    assert "From policy to plan" not in html and "Ingest" not in html          # no pipeline jargon on the home page
    assert html.count('class="cols__col') == 14 and "The app's first check" in html
    assert "data-cmdk-open" in html


def test_employee_home_uses_the_workspace_theme(corpus):
    client = current_app.test_client()
    login(client, "leila.haddad@aurelle.example")
    html = client.get("/dashboard/me").get_data(as_text=True)
    assert "theme-terra" in html and "css/learner.css" in html and "is-learner" in html
    assert "villa-dusk" not in html                                            # photo with glassware removed (no alcohol)


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
    team = client.get("/team/E001").get_data(as_text=True)
    assert 'value="approve"' in team and "Waiting for your sign-off" in team
    assert team.index("Waiting for your sign-off") < team.index("All tasks, situations and assessments")   # what needs Omar comes first


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


def test_search_finds_modules_by_title(corpus):
    from src.services import progress
    from tests.test_planning_pipeline import leila
    from tests.test_progress import assigned
    assigned()
    module = progress.assigned_plan(leila()).modules[0]
    word = max(module.title.split(), key=len)
    client = current_app.test_client()
    login(client, "leila.haddad@aurelle.example")                              # her own plan, opened as a learner
    mine = {g["label"]: g["items"] for g in client.get(f"/api/search?q={word}").get_json()["groups"]}
    assert any(i["url"] == f"/learn/{module.module_key}" for i in mine["Modules"])
    client.post("/logout")
    login(client, "training@aurelle.example")                                  # staff land on the plan page, at the module
    staff = {g["label"]: g["items"] for g in client.get(f"/api/search?q={word}").get_json()["groups"]}
    assert any(i["url"].endswith(f"#module-{module.module_key}") for i in staff["Modules"])


def test_work_sent_by_someone_without_a_line_manager_reaches_the_administrator(corpus):
    from database import db
    from src.services import progress
    from tests.test_planning_pipeline import leila
    from tests.test_progress import assigned, rows
    assigned()
    me = leila()
    plan = progress.assigned_plan(me)
    task = rows(plan)[0]
    status, task.status = task.status, "submitted"
    manager, me.reporting_manager_code = me.reporting_manager_code, None     # nobody to send it to
    db.session.commit()
    client = current_app.test_client()
    login(client, "admin@aurelle.example")
    home = client.get("/dashboard/admin").get_data(as_text=True)
    assert "Leila Haddad sent 1 task for sign-off, but has no line manager" in home
    assert "No line manager" in client.get("/employees").get_data(as_text=True)
    assert 'value="approve"' in client.get("/team/E001").get_data(as_text=True)     # the administrator can step in
    me.reporting_manager_code, task.status = manager, status                   # the shared data goes back as it was
    db.session.commit()


def test_a_finished_module_puts_its_assessment_at_the_top_for_the_manager(corpus):
    from database import db
    from src.services import progress
    from tests.test_planning_pipeline import leila
    from tests.test_progress import assigned, rows
    assigned()
    plan = progress.assigned_plan(leila())
    all_rows = rows(plan)
    target = next((r for r in all_rows if r.plan_item.item_type == "assessment"), None)
    assert target is not None
    module_id = target.plan_item.module_id
    for r in all_rows:                                                         # finish everything else in that module
        if r.plan_item.module_id == module_id and r.plan_item.item_type != "assessment":
            r.status = "completed"
    target.status, target.due_date = "not_started", None
    db.session.commit()
    client = current_app.test_client()
    login(client, "omar.siddiqui@aurelle.example")
    team = client.get("/team").get_data(as_text=True)
    assert "Leila Haddad" in team and "ready to mark" in team
    assert "ready to mark" in client.get("/dashboard/team").get_data(as_text=True)
    page = client.get("/team/E001").get_data(as_text=True)
    top = page[page.index('id="signoff"'):page.index("All tasks, situations and assessments")]
    assert "Module finished · ready to mark" in top and 'value="approve"' in top
