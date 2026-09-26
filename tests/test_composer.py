"""Settings the administrator composes in the browser: the employee home and which pages each role sees."""
import pytest
from flask import current_app

from src.services import workspace
from tests.conftest import login
from tests.test_progress import assigned

ADMIN = {"email": "admin@aurelle.example", "app_role": "admin"}


@pytest.fixture
def clean_settings(corpus):
    yield
    workspace.reset_employee_home(ADMIN)
    workspace.reset_pages(ADMIN)


def home_form(**changes):
    form = {"order": "modules,hero,glance,journey,upcoming,quote", "section_hero": "on", "section_glance": "on",
            "section_journey": "on", "section_upcoming": "on", "section_quote": "on",
            "slide_welcome": "on", "slide_next": "on", "slide_quiz": "on", "slide_certificate": "on",
            "slide_welcome_photo": "lobby", "slide_next_photo": "reception", "slide_quiz_photo": "pool",
            "slide_certificate_photo": "room", "welcome_line": "We are glad you are here.",
            "quote": "Every guest, every time.", "quote_by": "The Aurelle team", "quote_photo": "resort"}
    form.update(changes)
    return {k: v for k, v in form.items() if v is not None}


def test_only_the_administrator_composes(clean_settings):
    client = current_app.test_client()
    login(client, "admin@aurelle.example")
    assert client.get("/settings/employee-home").status_code == 200
    assert client.get("/settings/access").status_code == 200
    client.post("/logout")
    login(client, "training@aurelle.example")
    assert client.get("/settings/employee-home").status_code == 403
    assert client.post("/settings/access", data={}).status_code == 403


def test_employee_home_follows_the_composed_layout(clean_settings):
    assigned()
    admin = current_app.test_client()
    login(admin, "admin@aurelle.example")
    admin.post("/settings/employee-home", data=home_form(section_quote=None, slide_quiz=None, section_modules=None))
    leila = current_app.test_client()
    login(leila, "leila.haddad@aurelle.example")
    html = leila.get("/dashboard/me").get_data(as_text=True)
    assert html.index("Your modules") < html.index('class="lhero"')                  # modules moved to the top
    assert 'class="lquote"' not in html                                                # closing line switched off
    assert ">Quiz</button>" not in html and ">Certificate</button>" in html            # quiz slide switched off
    assert "We are glad you are here." in html and "photos/lobby.jpg" in html
    assert "Your modules" in html                                                      # cannot be switched off


def test_composer_rejects_bad_input_and_resets(clean_settings):
    client = current_app.test_client()
    login(client, "admin@aurelle.example")
    page = client.post("/settings/employee-home", data=home_form(quote_photo="../../secret"), follow_redirects=True)
    assert b"Choose one of the listed photos" in page.data
    none = {k: None for k in ("slide_welcome", "slide_next", "slide_quiz", "slide_certificate")}
    page = client.post("/settings/employee-home", data=home_form(**none), follow_redirects=True)
    assert b"Keep at least one slide" in page.data
    client.post("/settings/employee-home", data=home_form())
    assert workspace.employee_home()["quote"] == "Every guest, every time."
    client.post("/settings/employee-home", data={"reset": "1"})
    assert workspace.employee_home()["quote"] == workspace.DEFAULT_HOME["quote"]


def test_pages_each_role_sees(clean_settings):
    assigned()
    admin = current_app.test_client()
    login(admin, "admin@aurelle.example")
    form = {f"employee:{e}": "on" for e in workspace.default_pages("employee") if e != "learning.calendar"}
    form.update({f"training_manager:{e}": "on" for e in workspace.default_pages("training_manager")})
    form["training_manager:ground_truth.conflicts"] = "on"                          # give the trainer Conflicts
    form["manager:documents.index"] = "on"                                           # not allowed for managers
    form.update({f"reviewer:{e}": "on" for e in workspace.default_pages("reviewer")})
    form.update({f"manager:{e}": "on" for e in workspace.default_pages("manager")})
    admin.post("/settings/access", data=form)

    leila = current_app.test_client()
    login(leila, "leila.haddad@aurelle.example")
    home = leila.get("/dashboard/me").get_data(as_text=True)
    assert 'href="/learn/calendar"' not in home and 'href="/learn/progress"' in home
    assert leila.get("/learn/calendar").status_code == 403                           # removed means blocked
    assert leila.get("/learn").status_code == 200                                    # locked pages stay

    trainer = current_app.test_client()
    login(trainer, "training@aurelle.example")
    rules = trainer.get("/requirements").get_data(as_text=True)                     # offered as a tab under Rules
    assert '<a href="/conflicts" class="hubtab' in rules

    omar = current_app.test_client()
    login(omar, "omar.siddiqui@aurelle.example")
    assert 'href="/documents/"' not in omar.get("/dashboard/team").get_data(as_text=True)

    login(admin, "admin@aurelle.example")                                            # test clients share flask.g
    admin.post("/settings/access", data={"reset": "1"})
    login(leila, "leila.haddad@aurelle.example")
    assert leila.get("/learn/calendar").status_code == 200
