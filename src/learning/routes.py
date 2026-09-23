"""Employee learning (modules, checklist, tasks, quizzes) and manager sign-off (SRS Steps 50, 53)."""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from config.settings import today
from database import audit, db
from database.models import Chunk, Document, Employee, PlanItem, Progress, QuizAttempt
from src.rbac import has_permission, require_permission
from src.services import progress

bp = Blueprint("learning", __name__)


def _me():
    employee = db.session.scalar(select(Employee).where(Employee.employee_code == current_user.employee_code))
    if employee is None:
        abort(403)
    plan = progress.assigned_plan(employee)
    if plan is None:
        flash("Your plan has not been assigned yet.", "info")
        abort(redirect(url_for("main.employee_dashboard")))
    return employee, plan


def _module(plan, module_key):
    return next((m for m in plan.modules if m.module_key == module_key), None) or abort(404)


def _sources(items):
    keys = {(i.source_doc_id, i.source_section_id) for i in items if i.source_doc_id}
    out = {}
    if keys:
        for chunk, doc in db.session.execute(select(Chunk, Document).join(Document, Chunk.document_id == Document.id)
                                             .where(Document.status.in_(["active", "expired"]),
                                                    Document.doc_id.in_({k[0] for k in keys}))):
            if (doc.doc_id, chunk.section_id) in keys:
                out.setdefault((doc.doc_id, chunk.section_id), []).append(chunk)
    return out


@bp.route("/learn/<module_key>")
@require_permission("learning.view")
def module(module_key):
    employee, plan = _me()
    m = _module(plan, module_key)
    hidden = progress.rejected_items(plan)
    items = [i for i in m.items if i.id not in hidden]
    rows = {p.plan_item_id: p for p in db.session.scalars(select(Progress).where(Progress.plan_id == plan.id,
                                                                                  Progress.employee_id == employee.id))}
    attempts = db.session.scalars(select(QuizAttempt).where(QuizAttempt.employee_id == employee.id, QuizAttempt.plan_id == plan.id,
                                                            QuizAttempt.module_key == module_key).order_by(QuizAttempt.attempt_no)).all()
    return render_template("learning/module.html", plan=plan, m=m, items=items, rows=rows, attempts=attempts,
                           sources=_sources(items), completion=progress.completion_type, cfg=progress.cfg())


@bp.route("/learn/item/<int:item_id>/<action>", methods=["POST"])
@require_permission("learning.submit")
def item_action(item_id, action):
    employee, plan = _me()
    item = db.session.get(PlanItem, item_id) or abort(404)
    if item.module.plan_id != plan.id:
        abort(404)
    actor = audit.actor_from_user(current_user)
    try:
        if action == "done":
            progress.complete_checklist(employee, item, actor)
            flash("Marked as done.", "success")
        elif action == "submit":
            progress.submit_for_signoff(employee, item, request.form.get("note"), actor)
            flash("Submitted. Your manager will sign it off.", "success")
        else:
            abort(404)
    except progress.ProgressError as exc:
        flash(str(exc), "error")
    return redirect(url_for("learning.module", module_key=item.module.module_key) + f"#{item.item_key}")


@bp.route("/learn/<module_key>/quiz", methods=["GET", "POST"])
@require_permission("learning.submit")
def quiz(module_key):
    employee, plan = _me()
    m = _module(plan, module_key)
    questions = progress.quiz_questions(plan, module_key)
    if not questions:
        abort(404)
    if request.method == "POST":
        selections = {q.item_key: [int(v) for v in request.form.getlist(q.item_key) if v.isdigit()] for q in questions}
        try:
            attempt = progress.submit_quiz(employee, plan, module_key, selections, audit.actor_from_user(current_user))
        except progress.ProgressError as exc:
            flash(str(exc), "error")
            return redirect(url_for("learning.quiz", module_key=module_key))
        return render_template("learning/quiz_result.html", plan=plan, m=m, questions=questions, attempt=attempt,
                               by_key={a["item_key"]: a for a in attempt.answers}, sources=_sources(questions),
                               cfg=progress.cfg(), used=attempt.attempt_no)
    return render_template("learning/quiz.html", plan=plan, m=m, questions=questions, cfg=progress.cfg(),
                           used=progress.attempts_used(employee, plan, module_key))


# --------------------------------------------------------------------------- manager

def _can_manage(employee):
    if has_permission(current_user, "plans.view"):             # training manager, admin
        return True
    return has_permission(current_user, "progress.verify_team") and employee.reporting_manager_code == current_user.employee_code


@bp.route("/team/<code>")
@login_required
def team_member(code):
    employee = db.session.scalar(select(Employee).where(Employee.employee_code == code)) or abort(404)
    if not _can_manage(employee):
        abort(403)
    plan = progress.assigned_plan(employee)
    summary = progress.summary(plan, employee, today(current_app.config)) if plan else None
    rows = []
    if plan:
        rows = db.session.execute(select(Progress, PlanItem).join(PlanItem, Progress.plan_item_id == PlanItem.id)
                                  .where(Progress.plan_id == plan.id, Progress.employee_id == employee.id,
                                         PlanItem.item_type.in_(["task", "scenario", "assessment"]))
                                  .order_by(Progress.due_date, PlanItem.item_key)).all()
    return render_template("learning/team_member.html", employee=employee, plan=plan, summary=summary, rows=rows,
                           weak=progress.weak_requirements(employee, plan) if plan else {})


@bp.route("/team/progress/<int:pk>/signoff", methods=["POST"])
@login_required
def sign_off(pk):
    row = db.session.get(Progress, pk) or abort(404)
    employee = db.session.get(Employee, row.employee_id)
    if not _can_manage(employee):
        abort(403)
    score = request.form.get("score")
    try:
        progress.sign_off(row, audit.actor_from_user(current_user), request.form.get("decision") == "approve",
                          request.form.get("note", ""), float(score) if score not in (None, "") else None)
        flash("Recorded.", "success")
    except (progress.ProgressError, ValueError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("learning.team_member", code=employee.employee_code))
