"""Employees and onboarding plans: generate (Pipeline 1), inspect validation (Pipeline 2) and traceability."""
from collections import Counter

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select

from database import audit, db
from database.models import (Chunk, ComparisonRow, Document, Employee, Finding, GenerationRun, Plan,
                             ValidationRun)
from genai_pipeline.providers import ProviderError
from src.rbac import require_permission
from src.services import planning

bp = Blueprint("plans", __name__)


@bp.route("/employees")
@require_permission("plans.view")
def employees():
    people = db.session.scalars(select(Employee).order_by(Employee.employee_code)).all()
    latest = {}
    for p in db.session.scalars(select(Plan).order_by(Plan.version)):
        latest[p.employee_id] = p
    matrix = planning.current_matrix()
    return render_template("plans/employees.html", people=people, latest=latest, matrix=matrix)


@bp.route("/employees/<code>/generate", methods=["POST"])
@require_permission("plans.generate")
def generate(code):
    employee = db.session.scalar(select(Employee).where(Employee.employee_code == code)) or abort(404)
    try:
        plan = planning.generate_plan(employee, audit.actor_from_user(current_user), current_app.config)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("plans.employees"))
    except ProviderError as exc:
        flash(f"Gemini is not available ({exc.kind}): {exc}", "error")
        return redirect(url_for("plans.employees"))
    if plan.status == "Failed":
        flash(f"Generation failed and nothing was assigned: {plan.error}", "error")
    else:
        total = next((s["ms"] for s in plan.timeline if s["step"] == "Total"), 0) / 1000
        flash(f"Plan generated and validated in {total:.1f} s. Status: {plan.status}.", "success")
    return redirect(url_for("plans.plan_detail", pk=plan.id))


@bp.route("/plans/<int:pk>/consistency", methods=["POST"])
@require_permission("plans.generate")
def consistency(pk):
    plan = db.session.get(Plan, pk) or abort(404)
    try:
        planning.run_consistency(plan, current_app.config)
        flash(f"Consistency across {plan.consistency['runs']} runs: {plan.score_generation_consistency}%.", "success")
    except ProviderError as exc:
        flash(f"Gemini is not available ({exc.kind}).", "error")
    return redirect(url_for("plans.plan_detail", pk=pk))


@bp.route("/plans/<int:pk>")
@require_permission("plans.view")
def plan_detail(pk):
    plan = db.session.get(Plan, pk) or abort(404)
    run = db.session.scalar(select(ValidationRun).where(ValidationRun.plan_id == plan.id)
                            .order_by(ValidationRun.created_at.desc(), ValidationRun.id.desc()))
    findings = sorted(run.findings if run else [], key=lambda f: ({"error": 0, "warning": 1, "info": 2}[f.severity], f.rule_id))
    by_item = {}
    for f in findings:
        if f.item_key:
            by_item.setdefault(f.item_key, []).append(f)
    show = request.args.get("comparison", "mismatches")
    rows = sorted(run.comparison_rows if run else [], key=lambda r: (r.overall_match, r.req_id))
    if show == "mismatches":
        rows = [r for r in rows if not r.overall_match]
    cited = {(i.source_doc_id, i.source_section_id) for m in plan.modules for i in m.items if i.source_doc_id}
    sources = {}
    for chunk, doc in db.session.execute(select(Chunk, Document).join(Document, Chunk.document_id == Document.id)
                                         .where(Document.status.in_(["active", "expired"]))):
        if (doc.doc_id, chunk.section_id) in cited:
            sources.setdefault((doc.doc_id, chunk.section_id), []).append(chunk)
    runs = {r.id: r for r in db.session.scalars(select(GenerationRun).where(GenerationRun.plan_id == plan.id))}
    outline_runs = [r for r in runs.values() if r.phase == "outline"]
    severity = Counter(f.severity for f in findings)
    from src.services.review import plan_review_state
    review_state = plan_review_state(plan)
    review_by_item = {r.target_key: r for r in review_state["items"]}
    return render_template("plans/plan.html", plan=plan, run=run, findings=findings, by_item=by_item, rows=rows,
                           review_state=review_state, review_by_item=review_by_item,
                           show=show, sources=sources, runs=runs, outline_runs=outline_runs, severity=severity,
                           total_rows=len(run.comparison_rows) if run else 0)


@bp.route("/plans/<int:pk>/assign", methods=["POST"])
@require_permission("plans.assign")
def assign(pk):
    from src.services.review import ReviewError, assign_plan
    plan = db.session.get(Plan, pk) or abort(404)
    try:
        assign_plan(plan, audit.actor_from_user(current_user))
        flash(f"{plan.plan_code} v{plan.version} is assigned to {plan.employee.name}.", "success")
    except ReviewError as exc:
        flash(f"The plan cannot be assigned yet: {exc}", "error")
    return redirect(url_for("plans.plan_detail", pk=pk))
