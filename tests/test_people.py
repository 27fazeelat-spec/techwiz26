"""Job roles added at runtime and employee profiles (SRS FR iii-iv, Step 9; integrity challenge 3)."""
import pytest
from flask import current_app
from sqlalchemy import select

from database import db
from database.models import AuditLog, Employee, JobRole, MatrixRow, User
from src.services import people
from tests.conftest import login

ACTOR = {"email": "training@aurelle.example", "app_role": "training_manager"}
EMPLOYEE = {"employee_code": "E901", "name": "Test Person", "role_code": "FOA", "property_code": "DXB-HBR",
            "experience_level": "Beginner", "experience_years": "0", "joining_date": "2026-11-01",
            "reporting_manager_code": "M001", "shift_pattern": "night"}


def test_a_new_role_is_mapped_previewed_and_only_used_after_activation(corpus):
    role = people.create_role("NAU", "Night Auditor", "Front Office", "night auditor, night audit", ACTOR)
    assert role.status == "pending_mapping"
    preview = people.preview_mapping(role)
    assert preview["specific"] and preview["everyone"] > 0
    assert any("night audit" in r.text.lower() or "SOP-FO-02" == r.doc_id for r in preview["specific"])
    from src.services.matrix import build_draft
    before = build_draft(ACTOR)
    assert not db.session.scalar(select(MatrixRow).where(MatrixRow.matrix_version_id == before.id,
                                                         MatrixRow.job_role_id == role.id))   # pending: not used yet
    people.activate_role(role, ACTOR)
    after = build_draft(ACTOR)
    assert after.stats["per_role"].get("NAU", 0) >= len(preview["specific"])
    assert db.session.scalar(select(AuditLog).where(AuditLog.action == "role.activated", AuditLog.entity_id == "NAU"))
    with pytest.raises(people.PeopleError):
        people.create_role("NAU", "Another", "Front Office", "", ACTOR)                 # duplicate code
    with pytest.raises(people.PeopleError):
        people.create_role("N1", "Digits", "Front Office", "", ACTOR)                   # bad code


def test_employee_profiles_are_validated_and_audited(corpus):
    with pytest.raises(people.PeopleError):
        people.create_employee({**EMPLOYEE, "employee_code": "bad"}, ACTOR)
    with pytest.raises(people.PeopleError):
        people.create_employee({**EMPLOYEE, "joining_date": ""}, ACTOR)
    e = people.create_employee(EMPLOYEE, ACTOR)
    assert e.department == "Front Office" and e.shift_pattern == "night"            # department from the role
    people.update_employee(e, {**EMPLOYEE, "experience_level": "Advanced"}, ACTOR)
    assert e.experience_level == "Advanced"
    assert db.session.scalar(select(AuditLog).where(AuditLog.action == "employee.updated", AuditLog.entity_id == "E901"))
    assert not hasattr(Employee, "national_id") and not hasattr(Employee, "salary")  # no sensitive data (Step 9)


def test_people_pages_and_permissions(corpus):
    client = current_app.test_client()
    login(client, "training@aurelle.example")
    assert client.get("/roles").status_code == 200
    assert 'class="rolecard"' in client.get("/roles").get_data(as_text=True)
    response = client.post("/roles", data={"code": "PAT", "name": "Pool Attendant", "department": "Recreation",
                                           "aliases": "pool attendant, lifeguard"})
    assert response.status_code == 302
    assert client.get("/roles/PAT").status_code == 200
    assert client.get("/employees/new").status_code == 200
    assert client.get("/employees/E001/edit").status_code == 200
    client.post("/logout")
    login(client, "evaluator@aurelle.example")                                     # reviewers can look, not change
    assert client.get("/roles").status_code == 200
    assert client.post("/roles", data={"code": "XYZ", "name": "X", "department": "Y"}).status_code == 403
    assert client.get("/employees/new").status_code == 403


def test_set_password_command(corpus):
    runner = current_app.test_cli_runner()
    result = runner.invoke(args=["set-password", "leila.haddad@aurelle.example", "--generate"])
    assert result.exit_code == 0 and "New password:" in result.output
    new_password = result.output.rsplit("New password: ", 1)[1].strip()
    from src.auth.models import authenticate
    assert authenticate("leila.haddad@aurelle.example", new_password)[0] is not None
    runner.invoke(args=["set-password", "leila.haddad@aurelle.example"], input="correct-horse\ncorrect-horse\n")
    assert runner.invoke(args=["set-password", "nobody@example.com", "--generate"]).exit_code != 0


def test_admin_gives_a_new_employee_a_login_and_can_reset_it(corpus):
    client = current_app.test_client()
    login(client, "admin@aurelle.example")
    form = {**EMPLOYEE, "employee_code": "E951", "name": "Sana Mir"}
    assert b"Sign-in email" in client.get("/employees/new").data
    short = client.post("/employees/new", data={**form, "login_email": "sana@aurelle.example", "login_password": "short"},
                        follow_redirects=True)
    assert b"at least 10 characters" in short.data
    assert db.session.scalar(select(Employee).where(Employee.employee_code == "E951")) is None      # nothing half-saved
    taken = client.post("/employees/new", data={**form, "login_email": "admin@aurelle.example", "login_password": "long-enough-1"},
                        follow_redirects=True)
    assert b"already uses this email" in taken.data
    client.post("/employees/new", data={**form, "login_email": "Sana@Aurelle.example", "login_password": "first-password-1"})
    user = db.session.scalar(select(User).where(User.employee_code == "E951"))
    assert user.email == "sana@aurelle.example" and user.app_role == "employee"
    assert "first-password-1" not in user.password_hash
    entry = db.session.scalar(select(AuditLog).where(AuditLog.action == "user.created", AuditLog.entity_id == user.email))
    assert entry is not None and "password" not in str(entry.after)
    # the administrator resets it from the edit page; leaving it empty keeps the old one
    client.post("/employees/E951/edit", data={**form, "login_email": "sana@aurelle.example", "login_password": ""})
    client.post("/employees/E951/edit", data={**form, "login_email": "sana@aurelle.example", "login_password": "second-password-2"})
    client.post("/logout")
    assert b"incorrect" in login(client, "sana@aurelle.example", "first-password-1").data           # old password no longer works
    response = login(client, "sana@aurelle.example", "second-password-2")
    assert response.status_code == 302 and "/login" not in response.headers["Location"]


def test_only_the_administrator_sets_logins(corpus):
    client = current_app.test_client()
    login(client, "training@aurelle.example")
    page = client.get("/employees/new").get_data(as_text=True)
    assert "Sign-in email" not in page and "administrator sets up" in page
    client.post("/employees/new", data={**EMPLOYEE, "employee_code": "E952", "name": "No Login",
                                        "login_email": "sneaky@aurelle.example", "login_password": "trainer-made-1"})
    assert db.session.scalar(select(Employee).where(Employee.employee_code == "E952")) is not None
    assert db.session.scalar(select(User).where(User.email == "sneaky@aurelle.example")) is None     # fields ignored


def test_an_employee_who_leaves_drops_off_the_lists_but_the_record_stays(corpus):
    from datetime import date
    from flask import current_app, g
    from database import db
    from database.models import Employee, User
    from src.services import people
    from tests.conftest import login
    leila = db.session.scalar(select(Employee).where(Employee.employee_code == "E001"))
    temp = Employee(organization_id=leila.organization_id, employee_code="E990", name="Tara Temp", job_role_id=leila.job_role_id,
                    property_id=leila.property_id, department=leila.department, experience_level="Beginner",
                    experience_years=0, joining_date=date(2026, 10, 1), reporting_manager_code="M001")
    db.session.add(temp)
    db.session.commit()
    people.set_login(temp, "tara.temp@aurelle.example", "tara-pass-123", {"email": "admin@aurelle.example"})

    admin = current_app.test_client()
    g.pop("_login_user", None)
    login(admin, "admin@aurelle.example")
    admin.post("/employees/E990/left", data={"action": "left", "left_on": "2026-10-20", "reason": "Resigned"})
    db.session.refresh(temp)
    assert temp.left_on == date(2026, 10, 20) and temp.left_reason == "Resigned"
    assert not db.session.scalar(select(User).where(User.email == "tara.temp@aurelle.example")).active
    assert "E990" not in admin.get("/employees").get_data(as_text=True)               # hidden by default
    assert "E990" in admin.get("/employees?employment=left").get_data(as_text=True)
    assert "Tara Temp" not in admin.get("/dashboard/plans").get_data(as_text=True).split("flashes")[-1]
    assert admin.post("/employees/E990/generate").status_code == 302                  # refused, no plan made
    other = current_app.test_client()
    g.pop("_login_user", None)
    assert login(other, "tara.temp@aurelle.example", "tara-pass-123").status_code != 302   # login switched off

    g.pop("_login_user", None)
    login(admin, "admin@aurelle.example")
    admin.post("/employees/E990/left", data={"action": "return"})
    db.session.refresh(temp)
    assert temp.left_on is None and db.session.scalar(select(User).where(User.email == "tara.temp@aurelle.example")).active
    g.pop("_login_user", None)
