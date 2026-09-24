"""SkillSprint Console (for SkillSprint staff) and the sample employee view for demo visitors."""
import csv
import io
import re
from urllib.parse import quote

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_, select

import database
from database import audit, db, utcnow
from database.models import AuditLog, DemoAccount, DemoRequest, DemoVisit, Document, Employee, Organization, Plan, User
from src.rbac import require_permission
from src.services import demo, mailer

bp = Blueprint("console", __name__, url_prefix="/console")
tryout = Blueprint("tryout", __name__, url_prefix="/try")


@bp.before_request
@login_required
def only_skillsprint_staff():
    """The console belongs to SkillSprint. A client's administrator (who holds every workspace permission) is refused."""
    if current_user.app_role != "platform_admin":
        abort(403)


def _staff():
    return audit.actor_from_user(current_user)


@bp.route("/")
@require_permission("console.view")
def overview():
    counts = db.session.execute(select(
        select(func.count()).select_from(Organization).scalar_subquery(),
        select(func.count()).select_from(User).scalar_subquery(),
        select(func.count()).select_from(Plan).where(Plan.status != "superseded").scalar_subquery(),
    )).one()
    return render_template("console/overview.html", o=demo.overview(), orgs=counts[0], users=counts[1], plans=counts[2],
                           healthy=database.ping(), statuses=demo.STATUSES, page_name=demo.page_name, now=utcnow())


@bp.route("/requests")
@require_permission("console.view")
def requests():
    status, q = request.args.get("status", ""), (request.args.get("q") or "").strip()
    query = select(DemoRequest).order_by(DemoRequest.created_at.desc())
    if status in demo.STATUSES:
        query = query.where(DemoRequest.status == status)
    if q:
        like = f"%{q}%"
        query = query.where(or_(DemoRequest.company.ilike(like), DemoRequest.name.ilike(like), DemoRequest.email.ilike(like)))
    counts = dict(db.session.execute(select(DemoRequest.status, func.count()).group_by(DemoRequest.status)).all())
    return render_template("console/requests.html", rows=db.session.scalars(query.limit(300)).all(), status=status, q=q,
                           statuses=demo.STATUSES, counts=counts)


@bp.route("/requests.csv")
@require_permission("console.view")
def requests_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Received (UTC)", "Name", "Email", "Company", "Job title", "Size", "Country", "Status", "Message", "Note"])
    for r in db.session.scalars(select(DemoRequest).order_by(DemoRequest.created_at.desc())):
        w.writerow([r.created_at.strftime("%Y-%m-%d %H:%M"), r.name, r.email, r.company, r.job_title, r.company_size,
                    r.country, demo.STATUSES.get(r.status, r.status), r.message, r.note])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=demo-requests.csv"})


@bp.route("/requests/<int:pk>", methods=["GET", "POST"])
@require_permission("console.view")
def request_detail(pk):
    req = db.session.get(DemoRequest, pk) or abort(404)
    if request.method == "POST":
        try:
            action = request.form.get("action")
            if action == "status":
                demo.set_status(req, request.form.get("status"), _staff())
                flash("Status updated.", "success")
            elif action == "note":
                demo.set_note(req, request.form.get("note"), _staff())
                flash("Note saved.", "success")
            elif action == "approve":
                password = request.form.get("password") or ""
                account = demo.approve(req, request.form.get("email"), password, _staff())
                return _send_login(account, password)
            return redirect(url_for("console.request_detail", pk=pk))
        except demo.DemoError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    accounts = db.session.scalars(select(DemoAccount).where(DemoAccount.request_id == pk)).all()
    return render_template("console/request_detail.html", r=req, accounts=accounts, statuses=demo.STATUSES,
                           days=demo.DEMO_DAYS, min_password=demo.MIN_PASSWORD, now=utcnow(), is_live=demo.is_live)


def _send_login(account, password):
    """Email the login when the server can; otherwise hand the staff member a ready draft. Shown once."""
    subject, body = demo.email_text(account, password, url_for("auth.login", _external=True))
    sent, error = mailer.send(account.email, subject, body)
    audit.record("demo.login_emailed" if sent else "demo.login_draft", "demo_account", account.email, actor=_staff())
    mailto = f"mailto:{account.email}?subject={quote(subject)}&body={quote(body)}"
    return render_template("console/login_sent.html", account=account, sent=sent, error=error, subject=subject, body=body,
                           mailto=mailto)


@bp.route("/demos")
@require_permission("console.view")
def demos():
    accounts = db.session.scalars(select(DemoAccount).order_by(DemoAccount.created_at.desc())).all()
    return render_template("console/demos.html", accounts=accounts, visits=demo.visit_summary([a.id for a in accounts]),
                           now=utcnow(), is_live=demo.is_live)


@bp.route("/demos/<int:pk>", methods=["GET", "POST"])
@require_permission("console.view")
def demo_detail(pk):
    account = db.session.get(DemoAccount, pk) or abort(404)
    if request.method == "POST":
        if request.form.get("action") == "extend":
            demo.extend(account, _staff())
            flash(f"Extended by {demo.DEMO_DAYS} days.", "success")
        elif request.form.get("action") == "end":
            demo.end(account, _staff())
            flash("The demo has ended; the login no longer works.", "success")
        return redirect(url_for("console.demo_detail", pk=pk))
    visits = db.session.scalars(select(DemoVisit).where(DemoVisit.account_id == pk).order_by(DemoVisit.ts.desc()).limit(300)).all()
    top = db.session.execute(select(DemoVisit.endpoint, func.count()).where(DemoVisit.account_id == pk)
                             .group_by(DemoVisit.endpoint).order_by(func.count().desc()).limit(6)).all()
    return render_template("console/demo_detail.html", a=account, visits=visits, top=top, page_name=demo.page_name,
                           now=utcnow(), is_live=demo.is_live, days=demo.DEMO_DAYS)


@bp.route("/workspaces")
@require_permission("console.view")
def workspaces():
    """Figures only: SkillSprint staff do not read a client's policies, people or plans."""
    rows = []
    for org in db.session.scalars(select(Organization).order_by(Organization.name)):
        rows.append({"org": org,
                     "users": db.session.scalar(select(func.count()).select_from(User).where(User.organization_id == org.id)),
                     "employees": db.session.scalar(select(func.count()).select_from(Employee).where(Employee.organization_id == org.id)),
                     "documents": db.session.scalar(select(func.count(func.distinct(Document.doc_id)))),
                     "plans": db.session.scalar(select(func.count()).select_from(Plan).where(Plan.status != "superseded")),
                     "last": db.session.scalar(select(func.max(AuditLog.ts)))})
    return render_template("console/workspaces.html", rows=rows)


# --------------------------------------------------------------------------- demo visitors: a sample employee
@tryout.route("/employee")
@login_required
def employee():
    """What a new hire at the sample company sees, read from the sample database (demo visitors only)."""
    from database import demo_db
    if current_user.app_role != "demo" or not demo_db.active():
        abort(403)
    from config.settings import today
    from src.services import progress, workspace
    day = today(current_app.config)
    person = db.session.scalar(select(Employee).where(Employee.employee_code == demo_db.SAMPLE_EMPLOYEE)) or abort(404)
    plan = progress.assigned_plan(person)
    home = {**workspace.DEFAULT_HOME, "quote_by": demo_db.ORG_NAME, "quote_photo": "corridor",
            "slides": {"welcome": {"on": True, "photo": "kitchen"}, "next": {"on": True, "photo": "team"},
                       "quiz": {"on": True, "photo": "training"}, "certificate": {"on": True, "photo": "interior"}},
            "welcome_line": "Every lesson here comes from our own kitchen and service standards."}
    html = render_template("dashboard/employee.html", employee=person, plan=plan, today=day, cfg=progress.cfg(),
                           summary=progress.summary(plan, person, day) if plan else None,
                           stages=progress.stages_for(plan, person, day) if plan else [],
                           upcoming=progress.up_next(plan, person, limit=7) if plan else [],
                           home=home, caption=workspace.caption, learner_preview=True)
    # A preview, not the employee's own session: links into the learning pages go nowhere.
    return re.sub(r'href="/learn[^"]*"', 'href="#" aria-disabled="true" data-tip="Preview only"', html)
