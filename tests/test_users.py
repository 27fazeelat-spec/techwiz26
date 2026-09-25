"""Settings > Users: the administrator adds and manages staff logins, with guardrails."""
import pytest
from flask import current_app, g
from sqlalchemy import select

from database import db
from database.models import User
from src.services import users
from tests.conftest import login

ADMIN = {"email": "admin@aurelle.example", "app_role": "admin"}


@pytest.fixture(autouse=True)
def signed_out():
    yield
    from flask import has_app_context
    if has_app_context():
        g.pop("_login_user", None)


def test_only_the_administrator_manages_users(corpus):
    client = current_app.test_client()
    login(client, "training@aurelle.example")
    assert client.get("/settings/users").status_code == 403
    client.post("/logout")
    login(client, "admin@aurelle.example")
    page = client.get("/settings/users").get_data(as_text=True)
    assert "Who can sign in" in page and "evaluator@aurelle.example" in page and "leila.haddad" not in page


def test_admin_adds_a_reviewer_and_a_line_manager(corpus):
    admin = current_app.test_client()
    login(admin, "admin@aurelle.example")
    admin.post("/settings/users", data={"action": "add", "name": "Sana Reviewer", "email": "sana.r@aurelle.example",
                                        "role": "reviewer", "password": "reviewer-pass-1"})
    admin.post("/settings/users", data={"action": "add", "name": "Bilal Manager", "email": "bilal.m@aurelle.example",
                                        "role": "manager", "manager_code": "m777", "password": "manager-pass-1"})
    bilal = db.session.scalar(select(User).where(User.email == "bilal.m@aurelle.example"))
    assert bilal.app_role == "manager" and bilal.employee_code == "M777"
    assert "Bilal Manager · M777" in admin.get("/employees/new").get_data(as_text=True)     # pickable as line manager
    reviewer = current_app.test_client()
    g.pop("_login_user", None)
    assert login(reviewer, "sana.r@aurelle.example", "reviewer-pass-1").status_code == 302
    assert reviewer.get("/review").status_code == 200


def test_bad_input_is_refused(corpus):
    with pytest.raises(users.UserError, match="10 characters"):
        users.add("A", "short.pw@aurelle.example", "reviewer", "short", None, ADMIN)
    with pytest.raises(users.UserError, match="already exists"):
        users.add("A", "admin@aurelle.example", "reviewer", "long-enough-1", None, ADMIN)
    with pytest.raises(users.UserError, match="manager code"):
        users.add("A", "nocode@aurelle.example", "manager", "long-enough-1", "", ADMIN)
    with pytest.raises(users.UserError, match="already used"):
        users.add("A", "dupcode@aurelle.example", "manager", "long-enough-1", "M001", ADMIN)
    with pytest.raises(users.UserError, match="Choose a role"):
        users.add("A", "norole@aurelle.example", "employee", "long-enough-1", None, ADMIN)


def test_switching_off_signs_the_person_out(corpus):
    person = users.add("Temp Trainer", "temp.t@aurelle.example", "training_manager", "trainer-pass-1", None, ADMIN)
    client = current_app.test_client()
    login(client, "temp.t@aurelle.example", "trainer-pass-1")
    assert client.get("/dashboard/plans").status_code == 200
    users.set_active(person, False, ADMIN)
    g.pop("_login_user", None)
    assert client.get("/dashboard/plans").status_code == 302                  # sent back to the sign-in page
    assert login(client, "temp.t@aurelle.example", "trainer-pass-1").status_code != 302


def test_guardrails(corpus):
    admin = db.session.scalar(select(User).where(User.email == "admin@aurelle.example"))
    omar = db.session.scalar(select(User).where(User.email == "omar.siddiqui@aurelle.example"))
    with pytest.raises(users.UserError, match="your own"):
        users.set_active(admin, False, ADMIN)
    with pytest.raises(users.UserError, match="your own"):
        users.change_role(admin, "reviewer", None, ADMIN)
    with pytest.raises(users.UserError, match="active administrator"):
        users.set_active(admin, False, {"email": "someone.else@aurelle.example"})
    with pytest.raises(users.UserError, match="line manager of"):                # Leila still reports to Omar
        users.change_role(omar, "reviewer", None, ADMIN)
