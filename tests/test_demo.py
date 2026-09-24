"""Request a demo, the SkillSprint console and read-only demo accounts."""
from datetime import timedelta

from flask import current_app
from sqlalchemy import delete, select

from database import db, utcnow
from database.models import DemoAccount, DemoRequest, DemoVisit, PlatformStaff
from src.auth.models import hash_password
from tests.conftest import login

STAFF_EMAIL, STAFF_PASSWORD = "sales@skillsprint.example", "console-pass-1"
FORM = {"name": "Sara Khan", "email": "sara@pearlhotels.example", "company": "Pearl Hotels", "job_title": "Training Head",
        "company_size": "51-200", "country": "Oman", "message": "Policy updates, please.", "consent": "on"}


def fresh():
    db.session.execute(delete(DemoVisit))
    db.session.execute(delete(DemoAccount))
    db.session.execute(delete(DemoRequest))
    if not db.session.scalar(select(PlatformStaff).where(PlatformStaff.email == STAFF_EMAIL)):
        db.session.add(PlatformStaff(email=STAFF_EMAIL, name="Sana Sales", password_hash=hash_password(STAFF_PASSWORD)))
    db.session.commit()


def test_public_demo_form(corpus):
    fresh()
    client = current_app.test_client()
    assert client.get("/demo").status_code == 200
    assert b"Request a demo" in client.get("/").data
    bad = client.post("/demo", data={**FORM, "email": "not-an-email"}, follow_redirects=True)
    assert b"work email" in bad.data
    client.post("/demo", data={**FORM, "website": "http://spam.example"})           # bots fill the hidden field
    assert db.session.scalar(select(DemoRequest)) is None
    response = client.post("/demo", data=FORM)
    assert response.status_code == 302 and response.headers["Location"].endswith("/demo/thanks")
    req = db.session.scalar(select(DemoRequest))
    assert req.company == "Pearl Hotels" and req.status == "new" and req.consent
    for _ in range(4):
        client.post("/demo", data=FORM)
    limited = client.post("/demo", data=FORM, follow_redirects=True)                 # six in an hour is too many
    assert b"several requests" in limited.data


def test_console_is_for_skillsprint_staff_only(corpus):
    fresh()
    client = current_app.test_client()
    response = login(client, STAFF_EMAIL, STAFF_PASSWORD)
    assert response.status_code == 302
    assert client.get("/app").headers["Location"].endswith("/console/")
    assert b"Needs a reply" in client.get("/console/").data
    assert client.get("/dashboard/admin").status_code == 403                         # no client workspace
    assert client.get("/documents/").status_code == 403
    client.post("/logout")
    login(client, "admin@aurelle.example")
    assert client.get("/console/").status_code == 403


def test_approving_creates_a_read_only_demo_that_ends(corpus):
    fresh()
    public = current_app.test_client()
    public.post("/demo", data=FORM)
    req = db.session.scalar(select(DemoRequest))

    staff = current_app.test_client()
    login(staff, STAFF_EMAIL, STAFF_PASSWORD)
    short = staff.post(f"/console/requests/{req.id}", data={"action": "approve", "email": req.email, "password": "short"},
                       follow_redirects=True)
    assert b"at least 10 characters" in short.data
    page = staff.post(f"/console/requests/{req.id}", data={"action": "approve", "email": req.email, "password": "pearl-demo-2026"})
    html = page.get_data(as_text=True)
    assert "Demo login created" in html and "pearl-demo-2026" in html and "mailto:sara@pearlhotels.example" in html
    account = db.session.scalar(select(DemoAccount))
    assert account.expires_at > utcnow() + timedelta(days=6) and "pearl-demo-2026" not in account.password_hash
    db.session.refresh(req)
    assert req.status == "approved"

    visitor = current_app.test_client()
    login(visitor, req.email, "pearl-demo-2026")
    home = visitor.get("/dashboard/admin").get_data(as_text=True)
    assert "Demo access" in home and "read-only" in home
    assert visitor.post("/documents/upload", data={}).status_code == 403              # looks, never changes
    assert visitor.get("/settings/employee-home").status_code == 403
    sample = visitor.get("/try/employee").get_data(as_text=True)
    assert "Welcome</span>, Alex." in sample and "Harbour View" in sample
    assert "Aurelle" not in sample and "Leila" not in sample                          # no client data in the sample
    assert db.session.scalar(select(DemoVisit).where(DemoVisit.endpoint == "tryout.employee")) is not None

    login(staff, STAFF_EMAIL, STAFF_PASSWORD)                                        # test clients share flask.g
    detail = staff.get(f"/console/demos/{account.id}").get_data(as_text=True)
    assert "Employee view (sample)" in detail
    staff.post(f"/console/demos/{account.id}", data={"action": "end"})
    login(visitor, req.email, "pearl-demo-2026")
    ended = login(visitor, req.email, "pearl-demo-2026")
    assert b"demo has ended" in ended.data or b"incorrect" in ended.data
    login(staff, STAFF_EMAIL, STAFF_PASSWORD)
    staff.post(f"/console/demos/{account.id}", data={"action": "extend"})
    db.session.refresh(account)
    assert account.active and account.expires_at > utcnow() + timedelta(days=6)
