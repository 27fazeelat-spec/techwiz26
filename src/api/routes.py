"""Small JSON endpoints used by the interface (hover cards). Read-only."""
import time

from flask import Blueprint, abort, current_app, jsonify
from flask_login import current_user, login_required
from sqlalchemy import func, select

from config.loader import load_config
from database import db
from database.models import Chunk, Conflict, Document, JobRole, Requirement, ReviewItem
from src.rbac import has_permission
from src.ui_text import label

bp = Blueprint("api", __name__, url_prefix="/api")


def _stage(code):
    return {s["code"]: s["label"] for s in load_config("stages")["stages"]}.get(code, code)


def _current_requirement(req_id):
    rows = db.session.execute(select(Requirement, Document, Chunk)
                              .join(Document, Requirement.document_id == Document.id)
                              .join(Chunk, Requirement.chunk_id == Chunk.id)
                              .where(Requirement.req_id == req_id)).all()
    if not rows:
        return None
    rank = {"active": 0, "expired": 1, "scheduled": 2, "superseded": 3, "draft": 4}
    return min(rows, key=lambda r: (rank.get(r[1].status, 9), r[1].id * -1))


@bp.route("/ref/<kind>/<path:code>")
@login_required
def ref(kind, code):
    if kind in ("req", "doc", "conflict") and not has_permission(current_user, "requirements.view") \
            and not has_permission(current_user, "review.view"):
        abort(403)
    if kind == "review" and not has_permission(current_user, "review.view"):
        abort(403)

    if kind == "req":
        found = _current_requirement(code)
        if not found:
            abort(404)
        r, d, c = found
        roles = "All roles" if r.roles == ["ALL"] else ", ".join(
            n for (n,) in db.session.execute(select(JobRole.name).where(JobRole.code.in_(r.roles or [])))) or "—"
        where = f"section {r.section_id}" + (f", page {c.location['page_start']}" if (c.location or {}).get("page_start") else "")
        return jsonify(kind="req", code=r.req_id, title=r.text, source=f"{d.title} ({d.doc_id} v{d.version}), {where}",
                       badges=[("Mandatory" if r.mandatory else "Optional"), f"Due: {_stage(r.due_stage)}", r.req_type],
                       meta=f"Applies to: {roles}", status=label("doc", d.status)[0],
                       warn=d.status != "active" and label("doc", d.status)[1] or "")
    if kind == "doc":
        d = db.session.scalar(select(Document).where(Document.doc_id == code).order_by(
            (Document.status != "active"), Document.id.desc()))
        if d is None:
            abort(404)
        return jsonify(kind="doc", code=d.doc_id, title=d.title or d.doc_id,
                       source=f"{d.category} · version {d.version}", badges=[label("doc", d.status)[0]],
                       meta=label("doc", d.status)[1])
    if kind == "conflict":
        c = db.session.scalar(select(Conflict).where(Conflict.conflict_code == code))
        if c is None:
            abort(404)
        left, right = c.left, c.right
        state = {"manual_review": "Waiting for a reviewer", "auto_resolved": "Resolved by precedence",
                 "auto_resolved_warning": "Resolved by the life-safety rule", "resolved_by_reviewer": "Resolved by a reviewer"}
        return jsonify(kind="conflict", code=c.conflict_code, title=f"{left.doc_id} vs {right.doc_id}",
                       source=f"{left.doc_id}: {left.text}", meta=f"{right.doc_id}: {right.text}",
                       badges=[state.get(c.status, c.status)], decision=c.explanation)
    if kind == "review":
        pk = int(code.replace("RV-", "")) if code.replace("RV-", "").isdigit() else 0
        r = db.session.get(ReviewItem, pk) or abort(404)
        return jsonify(kind="review", code=f"RV-{r.id:05d}", title=label("item", r.original_status)[0],
                       source=f"{r.plan.employee.name} · {r.plan.plan_code} v{r.plan.version}",
                       meta=(r.reasons[0]["message"] if r.reasons else ""), badges=[r.status.capitalize()])
    abort(404)


def known_documents():
    """Document IDs for linking codes in page text; cached for five minutes (one query, not one per page)."""
    from database import demo_db
    cache = current_app.extensions.setdefault("ref_docs_" + demo_db.cache_key(), {"at": 0, "ids": []})
    if time.time() - cache["at"] > 300:
        cache["ids"] = sorted(set(db.session.scalars(select(Document.doc_id))))
        cache["at"] = time.time()
    return cache["ids"]


@bp.route("/search")
@login_required
def search():
    """Ctrl+K palette: a few matches per kind, each limited to what the viewer may open. Read-only."""
    from flask import request, url_for
    from sqlalchemy import or_
    from database.models import Employee, Plan
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"groups": []})
    like, groups = f"%{q}%", []
    if has_permission(current_user, "documents.view"):
        docs = db.session.scalars(select(Document).where(Document.status.in_(["active", "expired", "draft", "scheduled"]),
                                                         or_(Document.doc_id.ilike(like), Document.title.ilike(like)))
                                  .order_by(Document.doc_id, Document.id.desc()).limit(12)).all()
        seen, items = set(), []
        for d in docs:
            if d.doc_id not in seen and len(items) < 5:
                seen.add(d.doc_id)
                items.append({"title": d.title or d.doc_id, "code": f"{d.doc_id} v{d.version}", "meta": d.status,
                              "url": url_for("documents.detail", doc_id=d.doc_id, version=d.version)})
        groups.append({"label": "Documents", "items": items})
    if has_permission(current_user, "requirements.view"):
        reqs = db.session.execute(select(Requirement.id, Requirement.req_id, Requirement.text)
                                  .join(Document, Requirement.document_id == Document.id)
                                  .where(Document.status == "active", or_(Requirement.req_id.ilike(like), Requirement.text.ilike(like)))
                                  .order_by(Requirement.req_id).limit(6)).all()
        groups.append({"label": "Requirements", "items": [
            {"title": t[:90], "code": code, "url": url_for("ground_truth.requirement_detail", pk=pk)} for pk, code, t in reqs]})
    if has_permission(current_user, "plans.view"):
        people = db.session.scalars(select(Employee).where(or_(Employee.name.ilike(like), Employee.employee_code.ilike(like)))
                                    .order_by(Employee.employee_code).limit(6)).all()
        latest = dict(db.session.execute(select(Plan.employee_id, func.max(Plan.id)).where(
            Plan.employee_id.in_([e.id for e in people]), Plan.status.notin_(["superseded", "Failed"]))
            .group_by(Plan.employee_id)).all()) if people else {}
        groups.append({"label": "Employees", "items": [
            {"title": e.name, "code": e.employee_code, "meta": "left" if e.has_left else ("open plan" if e.id in latest else "no plan yet"),
             "url": url_for("plans.plan_detail", pk=latest[e.id]) if e.id in latest else url_for("plans.employees", q=e.employee_code)}
            for e in people]})
    elif has_permission(current_user, "employees.view_team") and current_user.employee_code:     # line managers: their own team
        team = db.session.scalars(select(Employee).where(Employee.reporting_manager_code == current_user.employee_code,
                                                         or_(Employee.name.ilike(like), Employee.employee_code.ilike(like)))
                                  .order_by(Employee.name).limit(6)).all()
        groups.append({"label": "My team", "items": [
            {"title": e.name, "code": e.employee_code, "meta": e.job_role.name,
             "url": url_for("learning.team_member", code=e.employee_code)} for e in team]})
    groups.append({"label": "Modules", "items": _module_matches(like)})
    if has_permission(current_user, "conflicts.view") or has_permission(current_user, "requirements.view"):
        found = db.session.scalars(select(Conflict).where(Conflict.conflict_code.ilike(like)).limit(4)).all()
        groups.append({"label": "Conflicts", "items": [
            {"title": c.conflict_code, "code": c.status.replace("_", " "), "url": url_for("ground_truth.conflicts") + f"#{c.conflict_code}"}
            for c in found]})
    return jsonify({"groups": [g for g in groups if g["items"]]})


def _module_matches(like):
    """Modules by title, category or key (SRS Step 61): staff search current plans, an employee their own plan."""
    from flask import url_for
    from sqlalchemy import or_
    from database.models import Employee, Plan, PlanModule
    from src.services import progress
    match = or_(PlanModule.title.ilike(like), PlanModule.category.ilike(like), PlanModule.module_key.ilike(like))
    if has_permission(current_user, "plans.view"):
        rows = db.session.execute(select(PlanModule, Plan, Employee).join(Plan, PlanModule.plan_id == Plan.id)
                                  .join(Employee, Plan.employee_id == Employee.id)
                                  .where(Plan.status.notin_(["superseded", "Failed"]), match)
                                  .order_by(Employee.employee_code, Plan.id.desc(), PlanModule.position).limit(20)).all()
        seen, items = set(), []
        for m, plan, e in rows:
            if (e.id, m.module_key) not in seen and len(items) < 6:
                seen.add((e.id, m.module_key))
                items.append({"title": m.title, "code": m.module_key, "meta": f"{e.employee_code} · {m.category}",
                              "url": url_for("plans.plan_detail", pk=plan.id) + f"#module-{m.module_key}"})
        return items
    if has_permission(current_user, "learning.view") and current_user.employee_code:
        employee = db.session.scalar(select(Employee).where(Employee.employee_code == current_user.employee_code))
        plan = progress.assigned_plan(employee) if employee else None
        if plan:
            found = db.session.scalars(select(PlanModule).where(PlanModule.plan_id == plan.id, match)
                                       .order_by(PlanModule.position).limit(6)).all()
            return [{"title": m.title, "code": m.module_key, "meta": m.category,
                     "url": url_for("learning.module", module_key=m.module_key)} for m in found]
    return []
