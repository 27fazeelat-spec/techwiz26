"""Job roles (including new roles added at runtime) and employee profiles (SRS FR iii-iv)."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import case, func, select

from database import audit, db
from database.models import Employee, JobRole, Property
from src.rbac import has_permission, require_permission
from src.services import people, users

bp = Blueprint("people", __name__)


def _actor():
    return audit.actor_from_user(current_user)


@bp.route("/roles", methods=["GET", "POST"])
@require_permission("roles.view")
def roles():
    if request.method == "POST":
        if not has_permission(current_user, "roles.create"):
            abort(403)
        try:
            role = people.create_role(request.form.get("code"), request.form.get("name"), request.form.get("department"),
                                      request.form.get("aliases"), _actor())
            flash(f"Role {role.code} created. Check which requirements it picks up, then activate it.", "success")
            return redirect(url_for("people.role_detail", code=role.code))
        except people.PeopleError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    counts = dict(db.session.execute(select(Employee.job_role_id, func.count()).where(Employee.left_on.is_(None))
                                     .group_by(Employee.job_role_id)).all())
    rows = db.session.scalars(select(JobRole).order_by(JobRole.status.desc(), JobRole.code)).all()
    return render_template("people/roles.html", rows=rows, counts=counts, form=request.form, stats=_role_stats())


def _role_stats():
    """Per role (SRS Step 52): required rules in the approved matrix and how far the role's new hires have got."""
    from flask import current_app
    from config.settings import today
    from database.models import MatrixRow, MatrixVersion, Plan
    from src.services import progress
    stats = {}
    matrix = db.session.scalar(select(MatrixVersion).where(MatrixVersion.status == "approved").order_by(MatrixVersion.version_no.desc()))
    if matrix:
        for role_id, total, mandatory in db.session.execute(
                select(MatrixRow.job_role_id, func.count(), func.sum(case((MatrixRow.mandatory.is_(True), 1), else_=0)))
                .where(MatrixRow.matrix_version_id == matrix.id).group_by(MatrixRow.job_role_id)):
            stats.setdefault(role_id, {})["rules"], stats[role_id]["mandatory"] = total, int(mandatory or 0)
    plans = db.session.scalars(select(Plan).where(Plan.status.notin_(["superseded", "Failed"]))).all()
    latest = {}
    for plan in sorted(plans, key=lambda x: x.version):
        latest[plan.employee_id] = plan
    assigned = [pl for pl in latest.values() if pl.approved_at]
    overview = progress.overview([pl.id for pl in assigned], today(current_app.config))
    for pl in latest.values():
        s = stats.setdefault(pl.job_role_id, {})
        s["plans"] = s.get("plans", 0) + 1
        if pl.score_coverage is not None:
            s.setdefault("coverage", []).append(pl.score_coverage)
    for pl in assigned:
        s, o = stats[pl.job_role_id], overview.get(pl.id, {})
        s["assigned"] = s.get("assigned", 0) + 1
        s.setdefault("progress", []).append(o.get("pct", 0))
        s["completed"] = s.get("completed", 0) + (1 if o.get("total") and o.get("done") == o.get("total") else 0)
    for s in stats.values():
        s["coverage"] = round(sum(s["coverage"]) / len(s["coverage"]), 1) if s.get("coverage") else None
        s["progress"] = round(sum(s["progress"]) / len(s["progress"])) if s.get("progress") else None
    return stats


@bp.route("/roles/<code>", methods=["GET", "POST"])
@require_permission("roles.view")
def role_detail(code):
    role = db.session.scalar(select(JobRole).where(JobRole.code == code)) or abort(404)
    if request.method == "POST":
        action = request.form.get("action")
        if not has_permission(current_user, "roles.edit"):
            abort(403)
        try:
            if action == "activate":
                preview = people.activate_role(role, _actor())
                flash(f"{role.name} is active with {len(preview['specific'])} role-specific requirements. "
                      "Build a new matrix draft and approve it to use them.", "success")
            else:
                people.update_role(role, request.form.get("name"), request.form.get("department"),
                                   request.form.get("aliases"), _actor())
                flash("Role saved.", "success")
        except people.PeopleError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("people.role_detail", code=code))
    employees = db.session.scalars(select(Employee).where(Employee.job_role_id == role.id).order_by(Employee.name)).all()
    return render_template("people/role_detail.html", role=role, preview=people.preview_mapping(role), employees=employees)


def _choices():
    return {"roles": db.session.scalars(select(JobRole).where(JobRole.status == "active").order_by(JobRole.name)).all(),
            "properties": db.session.scalars(select(Property).order_by(Property.name)).all(),
            "levels": people.LEVELS, "shifts": people.SHIFTS, "managers": users.managers(), "today": _today()}


def _today():
    from flask import current_app
    from config.settings import today
    return today(current_app.config)


@bp.route("/employees/new", methods=["GET", "POST"])
@require_permission("employees.create")
def employee_new():
    if request.method == "POST":
        try:
            email, password = people.check_login(request.form) if has_permission(current_user, "accounts.manage") else (None, None)
            e = people.create_employee(request.form, _actor())
            if email:
                people.set_login(e, email, password, _actor())
            flash(f"{e.name} added{' with a login for ' + email if email else ''}. Generate a plan when you are ready.", "success")
            return redirect(url_for("plans.employees"))
        except people.PeopleError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("people/employee_form.html", employee=None, form=request.form, login=None, **_choices())


@bp.route("/employees/<code>/edit", methods=["GET", "POST"])
@require_permission("employees.edit")
def employee_edit(code):
    employee = db.session.scalar(select(Employee).where(Employee.employee_code == code)) or abort(404)
    if request.method == "POST":
        try:
            email, password = people.check_login(request.form, employee) if has_permission(current_user, "accounts.manage") else (None, None)
            people.update_employee(employee, request.form, _actor())
            if email:
                people.set_login(employee, email, password, _actor())
            flash("Profile saved. Regenerate the plan if the role or experience changed.", "success")
            return redirect(url_for("plans.employees"))
        except people.PeopleError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    form = request.form if request.method == "POST" else {
        "name": employee.name, "role_code": employee.job_role.code, "property_code": employee.property.code,
        "department": employee.department, "experience_level": employee.experience_level,
        "experience_years": employee.experience_years, "previous_experience": employee.previous_experience or "",
        "joining_date": employee.joining_date.isoformat(), "reporting_manager_code": employee.reporting_manager_code or "",
        "shift_pattern": employee.shift_pattern, "certifications": ", ".join(employee.certifications or [])}
    login = people.login_for(employee)
    if request.method != "POST" and login:
        form = {**form, "login_email": login.email}
    return render_template("people/employee_form.html", employee=employee, form=form, login=login, **_choices())


@bp.route("/employees/<code>/left", methods=["POST"])
@require_permission("employees.edit")
def employee_left(code):
    employee = db.session.scalar(select(Employee).where(Employee.employee_code == code)) or abort(404)
    try:
        if request.form.get("action") == "return":
            people.mark_returned(employee, _actor())
            flash(f"{employee.name} is back: shown on the boards again and their login works.", "success")
        else:
            people.mark_left(employee, request.form.get("left_on"), request.form.get("reason"), _actor())
            flash(f"{employee.name} is marked as left. Their login is switched off; their plan, progress and audit "
                  "history are kept.", "success")
    except people.PeopleError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("people.employee_edit", code=code))
