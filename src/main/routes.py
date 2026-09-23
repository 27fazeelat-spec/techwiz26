from flask import Blueprint, jsonify, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func, or_, select

import database
from database import db
from database.models import (AuditLog, Chunk, Conflict, Document, Employee, JobRole, MatrixVersion, Plan, Requirement,
                             SecurityFinding)
from src.rbac import has_permission, require_permission

bp = Blueprint("main", __name__)

DOC_STATUSES = ["active", "scheduled", "superseded", "expired", "draft"]


@bp.route("/")
@login_required
def home():
    if has_permission(current_user, "dashboard.admin"):
        return redirect(url_for("main.admin_dashboard"))
    if has_permission(current_user, "dashboard.team"):
        return redirect(url_for("main.team_dashboard"))
    return redirect(url_for("main.employee_dashboard"))


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
    )).one()
    stats = {
        "documents": sum(counts.values()),
        "lineages": counters[0], "chunks": counters[1], "roles": counters[2], "employees": counters[3],
        "requirements": counters[4], "findings": counters[5], "quarantined": counters[6],
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
    recent = db.session.scalars(select(AuditLog).order_by(AuditLog.ts.desc()).limit(8)).all()
    attention = db.session.scalars(
        select(Document).where(or_(Document.status.in_(["expired", "draft"]), hidden))
        .order_by(Document.doc_id).limit(8)).all()
    return render_template("dashboard/admin.html", counts=counts, stats=stats, recent=recent,
                           attention=attention, statuses=DOC_STATUSES)


@bp.route("/dashboard/team")
@require_permission("dashboard.team")
def team_dashboard():
    from config.settings import today
    from flask import current_app
    from src.services import progress
    team = db.session.scalars(select(Employee).where(Employee.reporting_manager_code == current_user.employee_code)
                              .order_by(Employee.name)).all()
    states = {}
    for e in team:
        plan = progress.assigned_plan(e)
        states[e.id] = (plan, progress.summary(plan, e, today(current_app.config)) if plan else None)
    return render_template("dashboard/team.html", team=team, states=states, pending=progress.pending_signoffs(team))


@bp.route("/dashboard/me")
@require_permission("dashboard.employee")
def employee_dashboard():
    from config.settings import today
    from flask import current_app
    from src.services import progress
    employee = db.session.scalar(select(Employee).where(Employee.employee_code == current_user.employee_code))
    plan = progress.assigned_plan(employee) if employee else None
    summary = progress.summary(plan, employee, today(current_app.config)) if plan else None
    recs = progress.refresh_recommendations(employee, plan, today(current_app.config)) if plan else []
    return render_template("dashboard/employee.html", employee=employee, plan=plan, summary=summary, recs=recs)


@bp.route("/healthz")
def healthz():
    ok = database.ping()
    return jsonify({"status": "ok" if ok else "degraded", "database": ok}), (200 if ok else 503)
