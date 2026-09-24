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
    """Employees with their latest plan. Server-side filters (SRS FR lx): text, role, department, property,
    verification result of the latest plan, and progress status of the assigned plan."""
    from config.settings import today
    from database.models import JobRole, Property
    from src.services import progress
    args = {k: v for k, v in request.args.items() if v}
    query = select(Employee).join(JobRole, Employee.job_role_id == JobRole.id).order_by(Employee.employee_code)
    if args.get("q"):
        like = f"%{args['q'].strip()}%"
        query = query.where(Employee.name.ilike(like) | Employee.employee_code.ilike(like))
    if args.get("role"):
        query = query.where(JobRole.code == args["role"])
    if args.get("department"):
        query = query.where(Employee.department == args["department"])
    if args.get("property"):
        query = query.join(Property, Employee.property_id == Property.id).where(Property.code == args["property"])
    people = db.session.scalars(query).all()
    # Show the newest usable plan; a later failed attempt is flagged next to it, never shown in its place.
    latest, failed = {}, {}
    for p in db.session.scalars(select(Plan).where(Plan.status != "superseded").order_by(Plan.version)):
        if p.status == "Failed":
            failed[p.employee_id] = p
        else:
            latest[p.employee_id] = p
            failed.pop(p.employee_id, None)
    status = {}
    if args.get("progress"):
        day = today(current_app.config)
        for e in people:
            plan = progress.assigned_plan(e)
            status[e.id] = progress.summary(plan, e, day)["status"] if plan else "Not assigned"
        people = [e for e in people if status[e.id] == args["progress"]]
    if args.get("result"):
        want = args["result"]
        people = [e for e in people if (latest.get(e.id).status if latest.get(e.id) else "No plan") == want]
    matrix = planning.current_matrix()
    return render_template("plans/employees.html", people=people, latest=latest, failed=failed, matrix=matrix, args=args,
                           roles=db.session.scalars(select(JobRole).order_by(JobRole.code)).all(),
                           properties=db.session.scalars(select(Property).order_by(Property.name)).all(),
                           departments=sorted(set(db.session.scalars(select(Employee.department)))),
                           results=["No plan", "Verified", "Verified with Warning", "Incomplete", "Unsupported",
                                    "Contradictory", "Manual Review Required", "Failed"],
                           progress_statuses=["Not assigned"] + list(progress.cfg()["status_order"]))


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


@bp.route("/plans/compare")
@require_permission("plans.view")
def compare():
    options = db.session.scalars(select(Plan).where(Plan.status.notin_(["generating", "Failed"]))
                                 .order_by(Plan.plan_code, Plan.version.desc())).all()
    a = db.session.get(Plan, request.args.get("a", type=int)) if request.args.get("a") else None
    b = db.session.get(Plan, request.args.get("b", type=int)) if request.args.get("b") else None
    result = planning.compare_plans(a, b) if a and b else None
    return render_template("plans/compare.html", options=options, a=a, b=b, r=result)
