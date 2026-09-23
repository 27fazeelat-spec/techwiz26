"""Reports: preview in the browser, export as CSV, Excel or PDF (SRS FR lxi-lxii)."""
from flask import Blueprint, Response, abort, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import select

from database import audit, db
from database.models import Employee, JobRole
from src.rbac import has_permission
from src.services import reports

bp = Blueprint("reports", __name__)
PREVIEW_ROWS = 200


def _scope():
    """(allowed report names, employee_ids filter or None). Line managers see their own team only."""
    if has_permission(current_user, "reports.view"):
        return list(reports.REPORTS), None
    if has_permission(current_user, "reports.team"):
        ids = list(db.session.scalars(select(Employee.id).where(Employee.reporting_manager_code == current_user.employee_code)))
        return list(reports.TEAM_REPORTS), ids
    abort(403)


def _filters(employee_ids):
    role = request.args.get("role") or None
    return {"role": role, "employee_ids": employee_ids}


@bp.route("/reports")
@login_required
def index():
    names, _ = _scope()
    return render_template("reports/index.html", names=names)


@bp.route("/reports/<name>")
@login_required
def preview(name):
    names, ids = _scope()
    if name not in names:
        abort(404)
    table = reports.build(name, **_filters(ids))
    return render_template("reports/preview.html", t=table, rows=table.rows[:PREVIEW_ROWS], limit=PREVIEW_ROWS,
                           role=request.args.get("role", ""),
                           roles=db.session.scalars(select(JobRole).order_by(JobRole.code)).all())


@bp.route("/reports/<name>.<fmt>")
@login_required
def export(name, fmt):
    names, ids = _scope()
    if name not in names or fmt not in reports.FORMATS:
        abort(404)
    table = reports.build(name, **_filters(ids))
    mimetype, render = reports.FORMATS[fmt]
    body = render(table)
    audit.record("report.exported", "report", name, actor=audit.actor_from_user(current_user),
                 detail={"format": fmt, "rows": len(table.rows), "role": request.args.get("role")})
    filename = f"skillsprint_{name}_{table.generated_at:%Y%m%d_%H%M}.{fmt}"
    return Response(body, mimetype=mimetype, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
