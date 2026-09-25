from flask import Blueprint, jsonify, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func, or_, select

import database
from database import db
from database.models import (AuditLog, Chunk, Conflict, Document, Employee, JobRole, MatrixVersion, Plan, Requirement,
                             ReviewItem, SecurityFinding)
from src.rbac import has_permission, require_permission

bp = Blueprint("main", __name__)

DOC_STATUSES = ["active", "scheduled", "superseded", "expired", "draft"]


@bp.route("/app")
@login_required
def home():
    role = current_user.app_role
    if role == "platform_admin":
        return redirect(url_for("console.overview"))
    if role == "training_manager":
        return redirect(url_for("main.trainer_dashboard"))
    if role == "reviewer":
        return redirect(url_for("main.reviewer_dashboard"))
    if has_permission(current_user, "dashboard.admin"):
        return redirect(url_for("main.admin_dashboard"))
    if has_permission(current_user, "dashboard.team"):
        return redirect(url_for("main.team_dashboard"))
    return redirect(url_for("main.employee_dashboard"))


def _current_plans():
    """{employee_id: newest usable plan} and {employee_id: newest failed attempt after it}."""
    latest, failed = {}, {}
    for p in db.session.scalars(select(Plan).where(Plan.status != "superseded").order_by(Plan.version)):
        if p.status == "Failed":
            failed[p.employee_id] = p
        else:
            latest[p.employee_id] = p
            failed.pop(p.employee_id, None)
    return latest, failed


@bp.route("/dashboard/plans")
@require_permission("plans.view")
def trainer_dashboard():
    """The trainer's board: every employee in the column of the next thing their plan needs."""
    from flask import current_app
    from config.settings import today
    from database.models import ReviewItem
    from src.services import progress
    people = db.session.scalars(select(Employee).where(Employee.left_on.is_(None)).order_by(Employee.name)).all()
    latest, failed = _current_plans()
    open_by_plan = dict(db.session.execute(select(ReviewItem.plan_id, func.count())
                                           .where(ReviewItem.status == "open").group_by(ReviewItem.plan_id)).all())
    assigned_ids = [p.id for p in latest.values() if p.approved_at]
    prog = progress.overview(assigned_ids, today(current_app.config))
    columns = {"plan": [], "review": [], "assign": [], "learning": [], "done": []}
    for e in people:
        p = latest.get(e.id)
        if p is None:
            columns["plan"].append({"e": e, "p": None, "failed": failed.get(e.id)})
        elif p.approved_at:
            o = prog.get(p.id, {})
            columns["done" if o.get("total") and o.get("done") == o.get("total") else "learning"].append({"e": e, "p": p, "prog": o})
        elif open_by_plan.get(p.id):
            columns["review"].append({"e": e, "p": p, "open": open_by_plan[p.id]})
        else:
            columns["assign"].append({"e": e, "p": p})
    columns["plan"].sort(key=lambda c: c["e"].joining_date)             # whoever joins first needs a plan first
    covs = [p.score_coverage for p in latest.values() if p.score_coverage is not None]
    stats = {"people": len(people), "plans": len(latest), "waiting": sum(open_by_plan.get(p.id, 0) for p in latest.values()),
             "assigned": len(assigned_ids), "coverage": round(sum(covs) / len(covs), 1) if covs else None,
             "matrix": db.session.scalar(select(MatrixVersion).where(MatrixVersion.status == "approved")
                                         .order_by(MatrixVersion.version_no.desc()))}
    return render_template("dashboard/trainer.html", columns=columns, stats=stats, today=today(current_app.config))


@bp.route("/dashboard/review")
@require_permission("review.view")
def reviewer_dashboard():
    from database.models import Conflict, ReviewItem
    from src.ui_text import label
    open_items = db.session.execute(select(ReviewItem.original_status, func.count()).join(Plan)
                                    .where(ReviewItem.status == "open", Plan.status != "superseded")
                                    .group_by(ReviewItem.original_status)).all()
    by_plan = db.session.execute(select(Plan, func.count(ReviewItem.id)).join(ReviewItem, ReviewItem.plan_id == Plan.id)
                                 .where(ReviewItem.status == "open", Plan.status != "superseded")
                                 .group_by(Plan.id).order_by(func.count(ReviewItem.id).desc())).all()
    conflicts = db.session.scalars(select(Conflict).where(Conflict.status == "manual_review")).all()
    mine = db.session.scalars(select(ReviewItem).where(ReviewItem.decision_by == current_user.email)
                              .order_by(ReviewItem.decision_at.desc()).limit(6)).all()
    decided_total = db.session.scalar(select(func.count()).select_from(ReviewItem)
                                      .where(ReviewItem.decision_by == current_user.email)) or 0
    kinds = [(k, n, label("item", k)) for k, n in sorted(open_items, key=lambda kv: -kv[1])]
    from config.settings import today
    from flask import current_app
    return render_template("dashboard/reviewer.html", kinds=kinds, total=sum(n for _, n in open_items), by_plan=by_plan,
                           conflicts=conflicts, mine=mine, decided_total=decided_total, today=today(current_app.config))


@bp.route("/dashboard/admin")
@require_permission("dashboard.admin")
def admin_dashboard():
    counts = dict(db.session.execute(select(Document.status, func.count()).group_by(Document.status)).all())
    counts = {s: counts.get(s, 0) for s in DOC_STATUSES}
    hidden = Document.parse["hidden_blocks"].as_integer() > 0
    # Every counter in one statement: each round trip to the hosted database costs ~0.6 s.
    sub = lambda q: q.scalar_subquery()
    counters = db.session.execute(select(
        sub(select(func.count(func.distinct(Document.doc_id)))),
        sub(select(func.count()).select_from(Chunk).where(Chunk.doc_status == "active")),
        sub(select(func.count()).select_from(JobRole)),
        sub(select(func.count()).select_from(Employee)),
        sub(select(func.count()).select_from(Requirement).join(Document).where(Document.status.in_(["active", "expired"]))),
        sub(select(func.count()).select_from(SecurityFinding)),
        sub(select(func.count()).select_from(Chunk).where(Chunk.quarantined)),
        sub(select(func.count()).select_from(ReviewItem).where(ReviewItem.status == "open")),
    )).one()
    stats = {
        "documents": sum(counts.values()),
        "lineages": counters[0], "chunks": counters[1], "roles": counters[2], "employees": counters[3],
        "requirements": counters[4], "findings": counters[5], "quarantined": counters[6], "review_open": counters[7],
        "matrix": db.session.scalar(select(MatrixVersion).where(MatrixVersion.status == "approved")),
        "matrix_draft": db.session.scalar(select(MatrixVersion).where(MatrixVersion.status == "draft")
                                          .order_by(MatrixVersion.version_no.desc())),
    }
    # One aggregate query per table: every round trip to the hosted database costs ~0.6 s.
    conflicts = db.session.execute(select(
        func.count(), func.coalesce(func.sum(case((Conflict.status == "manual_review", 1), else_=0)), 0))
        .where(Conflict.kind == "cross_document")).one()
    stats["conflicts"], stats["conflicts_open"] = conflicts
    plans = db.session.execute(select(
        func.count(), func.coalesce(func.sum(case((Plan.status.in_(["Verified", "Verified with Warning"]), 1), else_=0)), 0))
        .where(Plan.status != "superseded")).one()
    stats["plans"], stats["plans_verified"] = plans
    plan_mix = dict(db.session.execute(select(Plan.status, func.count()).where(Plan.status != "superseded")
                                       .group_by(Plan.status)).all())
    role_cov = db.session.execute(select(JobRole.code, JobRole.name, func.avg(Plan.score_coverage), func.count(Plan.id))
                                  .join(Plan, Plan.job_role_id == JobRole.id)
                                  .where(Plan.status.notin_(["superseded", "Failed"]))
                                  .group_by(JobRole.code, JobRole.name).order_by(JobRole.code)).all()
    # Consecutive entries of the same action by the same person read as one line ("Review approved x7").
    recent = []
    for e in db.session.scalars(select(AuditLog).order_by(AuditLog.ts.desc()).limit(60)):
        who = (e.actor or {}).get("email") or (e.actor or {}).get("user_id")
        if recent and recent[-1]["action"] == e.action and recent[-1]["who"] == who:
            recent[-1]["count"] += 1
            recent[-1]["first"] = e
        elif len(recent) < 8:
            recent.append({"action": e.action, "who": who, "last": e, "first": e, "count": 1})
        else:
            break
    attention = db.session.scalars(
        select(Document).where(or_(Document.status.in_(["expired", "draft"]), hidden))
        .order_by(Document.doc_id).limit(8)).all()
    from config.settings import today
    from flask import current_app
    return render_template("dashboard/admin.html", counts=counts, stats=stats, recent=recent, today=today(current_app.config),
                           attention=attention, statuses=DOC_STATUSES, plan_mix=plan_mix, role_cov=role_cov)


@bp.route("/dashboard/team")
@require_permission("dashboard.team")
def team_dashboard():
    from config.settings import today
    from flask import current_app
    from src.services import progress
    team = db.session.scalars(select(Employee).where(Employee.reporting_manager_code == current_user.employee_code,
                                                     Employee.left_on.is_(None)).order_by(Employee.name)).all()
    states = {}
    for e in team:
        plan = progress.assigned_plan(e)
        states[e.id] = (plan, progress.summary(plan, e, today(current_app.config)) if plan else None)
    return render_template("dashboard/team.html", team=team, states=states, pending=progress.pending_signoffs(team),
                           today=today(current_app.config))


@bp.route("/dashboard/me")
@require_permission("dashboard.employee")
def employee_dashboard():
    from config.settings import today
    from flask import current_app
    from src.services import progress, workspace
    employee = db.session.scalar(select(Employee).where(Employee.employee_code == current_user.employee_code))
    if employee is None and current_user.app_role != "employee":
        return redirect(url_for("main.home"))                       # staff without an employee profile: their own home
    plan = progress.assigned_plan(employee) if employee else None
    summary = progress.summary(plan, employee, today(current_app.config)) if plan else None
    day = today(current_app.config)
    recs = progress.refresh_recommendations(employee, plan, day) if plan else []
    stages = progress.stages_for(plan, employee, day) if plan else []
    upcoming = progress.up_next(plan, employee, limit=7) if plan else []
    return render_template("dashboard/employee.html", employee=employee, plan=plan, summary=summary, recs=recs,
                           stages=stages, upcoming=upcoming, today=day, cfg=progress.cfg(),
                           home=workspace.employee_home(), caption=workspace.caption)


@bp.route("/healthz")
def healthz():
    ok = database.ping()
    return jsonify({"status": "ok" if ok else "degraded", "database": ok}), (200 if ok else 503)
