"""Demo requests from the public site and the temporary read-only accounts SkillSprint gives them.

A request is followed up in the console (new, contacted, booked, approved, won, lost). Approving creates a demo
account with a password the SkillSprint staff member chooses; it works for a fixed number of days, can only look,
and every page it opens is listed for the staff (the request form says so).
"""
import hashlib
import re
from datetime import timedelta

from sqlalchemy import func, select

from database import audit, db, utcnow
from database.models import DemoAccount, DemoRequest, DemoVisit, PlatformStaff, User

STATUSES = {"new": "New", "contacted": "Contacted", "booked": "Demo booked", "approved": "Demo access given",
            "won": "Won", "lost": "Lost"}
SIZES = ("1-50", "51-200", "201-1000", "1000+")
DEMO_DAYS = 7
MIN_PASSWORD = 10
MAX_PER_HOUR = 5
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LIMITS = {"name": 200, "email": 254, "company": 200, "job_title": 120, "country": 80, "message": 2000}


class DemoError(ValueError):
    pass


def _clean(form, key):
    return " ".join((form.get(key) or "").split())[:LIMITS.get(key, 200)]


def ip_hash(ip, secret):
    return hashlib.sha256(f"{secret}:{ip or ''}".encode()).hexdigest()


def create_request(form, ip_digest):
    """Validate and store a request. Bots that fill the hidden field get a normal-looking reply and nothing stored."""
    if (form.get("website") or "").strip():
        return None
    data = {k: _clean(form, k) for k in LIMITS}
    data["email"] = data["email"].lower()
    data["message"] = (form.get("message") or "").strip()[:LIMITS["message"]]
    if not data["name"] or not data["company"]:
        raise DemoError("Please tell us your name and your company.")
    if not EMAIL.match(data["email"]):
        raise DemoError("Please enter a work email we can reply to.")
    size = form.get("company_size") or ""
    if size not in SIZES:
        raise DemoError("Please choose the size of your company.")
    if form.get("consent") != "on":
        raise DemoError("Please agree that we may contact you about the demo.")
    hour_ago = utcnow() - timedelta(hours=1)
    recent = db.session.scalar(select(func.count()).select_from(DemoRequest)
                               .where(DemoRequest.ip_hash == ip_digest, DemoRequest.created_at >= hour_ago)) or 0
    if recent >= MAX_PER_HOUR:
        raise DemoError("We have already received several requests from this connection. Please try again later.")
    req = DemoRequest(company_size=size, consent=True, ip_hash=ip_digest, **data)
    db.session.add(req)
    db.session.flush()
    audit.record("demo.requested", "demo_request", req.id, actor={"user_id": "public", "app_role": "visitor"},
                 after={"company": req.company, "size": size}, commit=False)
    db.session.commit()
    return req


def set_status(req, status, staff):
    if status not in STATUSES:
        raise DemoError("Unknown status.")
    before = req.status
    req.status, req.handled_by, req.updated_at = status, staff["email"], utcnow()
    audit.record("demo.status", "demo_request", req.id, actor=staff, before={"status": before}, after={"status": status},
                 commit=False)
    db.session.commit()


def set_note(req, note, staff):
    req.note, req.updated_at = (note or "").strip()[:4000], utcnow()
    audit.record("demo.note", "demo_request", req.id, actor=staff, commit=False)
    db.session.commit()


def email_in_use(email):
    return any(db.session.scalar(select(m.id).where(m.email == email)) for m in (User, PlatformStaff, DemoAccount))


def approve(req, email, password, staff, days=DEMO_DAYS):
    """Create the demo account for a request. The password is used once to build the email and never stored."""
    email = (email or "").strip().lower()
    if not EMAIL.match(email):
        raise DemoError("Enter the email the demo login should use.")
    if len(password or "") < MIN_PASSWORD:
        raise DemoError(f"The password needs at least {MIN_PASSWORD} characters.")
    if email_in_use(email):
        raise DemoError("An account with this email already exists.")
    from src.auth.models import hash_password
    account = DemoAccount(request_id=req.id, email=email, name=req.name, company=req.company,
                          password_hash=hash_password(password), expires_at=utcnow() + timedelta(days=days),
                          created_by=staff["email"])
    db.session.add(account)
    req.status, req.handled_by, req.updated_at = "approved", staff["email"], utcnow()
    db.session.flush()
    audit.record("demo.account_created", "demo_account", email, actor=staff,
                 after={"request": req.id, "days": days}, commit=False)
    db.session.commit()
    return account


def extend(account, staff, days=DEMO_DAYS):
    start = max(account.expires_at, utcnow())
    account.expires_at, account.active = start + timedelta(days=days), True
    audit.record("demo.extended", "demo_account", account.email, actor=staff, after={"until": account.expires_at.isoformat()},
                 commit=False)
    db.session.commit()


def end(account, staff):
    account.active, account.expires_at = False, min(account.expires_at, utcnow())
    audit.record("demo.ended", "demo_account", account.email, actor=staff, commit=False)
    db.session.commit()


def is_live(account, now=None):
    return account.active and account.expires_at > (now or utcnow())


def email_text(account, password, login_url):
    subject = "Your SkillSprint demo"
    body = (f"Hello {account.name.split()[0]},\n\n"
            f"Thank you for your interest in SkillSprint. Your demo access is ready.\n\n"
            f"Sign in: {login_url}\nEmail: {account.email}\nPassword: {password}\n\n"
            f"The demo is read-only and works until {account.expires_at.strftime('%d %B %Y')}. It opens a sample hotel "
            f"workspace, and 'See it as an employee' shows what a new hire sees. During the demo we record which pages "
            f"you open, so we can follow up with what interests you.\n\n"
            f"Reply to this email if you have any questions.\n\nThe SkillSprint team")
    return subject, body


def overview(now=None):
    now = now or utcnow()
    week_ago = now - timedelta(days=7)
    counts = dict(db.session.execute(select(DemoRequest.status, func.count()).group_by(DemoRequest.status)).all())
    live = db.session.scalars(select(DemoAccount).where(DemoAccount.active.is_(True), DemoAccount.expires_at > now)
                              .order_by(DemoAccount.expires_at)).all()
    return {
        "new": counts.get("new", 0), "won": counts.get("won", 0), "counts": counts,
        "this_week": db.session.scalar(select(func.count()).select_from(DemoRequest).where(DemoRequest.created_at >= week_ago)) or 0,
        "live": live, "ending": [a for a in live if a.expires_at <= now + timedelta(days=2)],
        "new_requests": db.session.scalars(select(DemoRequest).where(DemoRequest.status == "new")
                                           .order_by(DemoRequest.created_at.desc()).limit(6)).all(),
        "activity": db.session.execute(select(DemoVisit, DemoAccount).join(DemoAccount, DemoVisit.account_id == DemoAccount.id)
                                       .order_by(DemoVisit.ts.desc()).limit(8)).all(),
    }


def visit_summary(account_ids):
    """{account_id: (visits, distinct pages)} in one query."""
    if not account_ids:
        return {}
    rows = db.session.execute(select(DemoVisit.account_id, func.count(), func.count(func.distinct(DemoVisit.endpoint)))
                              .where(DemoVisit.account_id.in_(account_ids)).group_by(DemoVisit.account_id)).all()
    return {a: (n, d) for a, n, d in rows}


PAGE_NAMES = {"main.admin_dashboard": "Overview", "main.trainer_dashboard": "Plans board", "plans.employees": "Employees & plans",
              "plans.plan_detail": "A plan", "plans.compare": "Plan comparison", "review.queue": "Review queue",
              "review.detail": "A review item", "documents.index": "Documents", "documents.detail": "A document",
              "changes.index": "Policy changes", "changes.detail": "A policy change", "ground_truth.security": "Security scan",
              "ground_truth.requirements": "Requirements", "ground_truth.requirement_detail": "A requirement",
              "ground_truth.conflicts": "Conflicts", "ground_truth.matrix_index": "Role matrix",
              "ground_truth.matrix_view": "A matrix version", "people.roles": "Job roles", "people.role_detail": "A job role",
              "reports.index": "Reports", "tryout.employee": "Employee view (sample)", "learning.team_member": "An employee's progress"}


def page_name(endpoint):
    return PAGE_NAMES.get(endpoint, endpoint.replace("_", " ").replace(".", " · "))
