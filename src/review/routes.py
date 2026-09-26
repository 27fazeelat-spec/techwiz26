"""Review queue and reviewer decisions (SRS Steps 48-49)."""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select

from database import audit, db
from database.models import Chunk, Document, Plan, ReviewItem
from genai_pipeline.providers import ProviderError
from src.rbac import has_permission, require_permission
from src.services import review

bp = Blueprint("review", __name__)


@bp.route("/review")
@require_permission("review.view")
def queue():
    show = request.args.get("show", "open")
    query = (select(ReviewItem, Plan).join(Plan, ReviewItem.plan_id == Plan.id)
             .where(Plan.status != "superseded").order_by(ReviewItem.created_at, ReviewItem.id))
    if show == "open":
        query = query.where(ReviewItem.status == "open")
    elif show == "decided":
        query = query.where(ReviewItem.status != "open")
    kind = request.args.get("kind", "")
    if request.args.get("plan", type=int):
        query = query.where(ReviewItem.plan_id == request.args.get("plan", type=int))
    rows = db.session.execute(query).all()
    kinds = {}
    for r, _ in rows:
        kinds[r.original_status] = kinds.get(r.original_status, 0) + 1
    if kind:
        rows = [(r, p) for r, p in rows if r.original_status == kind]
    # The rule or item in plain words, looked up in one query for the whole page.
    from database.models import Document, Requirement
    keys = {r.target_key for r, _ in rows if r.target_type == "requirement"}
    texts = {}
    if keys:
        for req, status in db.session.execute(select(Requirement, Document.status).join(Document)
                                              .where(Requirement.req_id.in_(keys))):
            if req.req_id not in texts or status == "active":
                texts[req.req_id] = req.text
    for r, _ in rows:
        if r.target_type == "plan_item" and r.plan_item is not None:
            c = r.plan_item.content
            texts[r.target_key] = c.get("text") or c.get("question") or c.get("activity") or c.get("description") or c.get("situation") or c.get("topic")
    return render_template("review/queue.html", rows=rows, show=show, counts=review.queue_counts(), kinds=kinds,
                           kind=kind, plan_filter=request.args.get("plan", type=int),
                           bulk_reason=review.BULK_REASONS.get(kind, ""), texts=texts)


@bp.route("/review/bulk", methods=["POST"])
@require_permission("review.decide")
def bulk():
    ids = [int(x) for x in request.form.getlist("item") if x.isdigit()]
    items = db.session.scalars(select(ReviewItem).where(ReviewItem.id.in_(ids))).all() if ids else []
    if not items:
        flash("Select at least one item.", "error")
        return redirect(request.referrer or url_for("review.queue"))
    try:
        done = review.decide_many(items, request.form.get("action", "approve"), audit.actor_from_user(current_user),
                                  request.form.get("reason"))
    except review.ReviewError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("review.queue"))
    flash(f"{done} item{'s' if done != 1 else ''} decided with one reason. Each decision is in the audit trail.", "success")
    return redirect(request.referrer or url_for("review.queue"))


@bp.route("/review/<int:pk>")
@require_permission("review.view")
def detail(pk):
    r = db.session.get(ReviewItem, pk) or abort(404)
    item = r.plan_item
    sources = []
    doc_id = item.source_doc_id if item else None
    section = item.source_section_id if item else None
    if r.target_type == "requirement":
        from database.models import Requirement
        req = db.session.scalar(select(Requirement).join(Document).where(
            Requirement.req_id == r.target_key, Document.status.in_(["active", "expired"])))
        if req:
            doc_id, section = req.doc_id, req.section_id
    if doc_id:
        sources = db.session.scalars(select(Chunk).join(Document, Chunk.document_id == Document.id).where(
            Document.doc_id == doc_id, Chunk.section_id == section, Document.status.in_(["active", "expired"]))).all()
    history = []
    prior = r
    while prior.carried_from_id:
        prior = db.session.get(ReviewItem, prior.carried_from_id)
        history.append(prior)
    # The next waiting item in the same plan, for "Skip": the one after this, else the first still waiting.
    waiting = db.session.scalars(select(ReviewItem.id).where(ReviewItem.plan_id == r.plan_id, ReviewItem.status == "open",
                                                             ReviewItem.id != r.id).order_by(ReviewItem.id)).all()
    skip_to = next((i for i in waiting if i > r.id), waiting[0] if waiting else None)
    return render_template("review/detail.html", r=r, item=item, sources=sources, history=history,
                           fields=review.editable_fields(item) if item else [],
                           override_statuses=review.cfg()["override_statuses"], code=review.code(r),
                           state=review.plan_review_state(r.plan), s=review.suggestion(r), skip_to=skip_to)


@bp.route("/review/<int:pk>/decide", methods=["POST"])
@require_permission("review.decide")
def decide(pk):
    r = db.session.get(ReviewItem, pk) or abort(404)
    action = request.form.get("action", "")
    if action == "override" and not has_permission(current_user, "review.override"):
        abort(403)
    try:
        message, plan = review.decide(r, action, audit.actor_from_user(current_user), request.form, current_app.config)
    except review.ReviewError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("review.detail", pk=pk))
    except (ProviderError, ValueError) as exc:
        db.session.rollback()
        flash(f"Regeneration did not run: {exc}", "error")
        return redirect(url_for("review.detail", pk=pk))
    flash(message, "success")
    if action == "regenerate":
        return redirect(url_for("plans.plan_detail", pk=plan.id))
    nxt = db.session.scalar(select(ReviewItem).where(ReviewItem.plan_id == r.plan_id, ReviewItem.status == "open")
                            .order_by(ReviewItem.id))
    if action != "comment" and request.form.get("then") == "next":
        if nxt is not None:
            return redirect(url_for("review.detail", pk=nxt.id))
        done = plan or r.plan
        flash(f"Every item in {done.employee.name}'s plan has a decision.", "success")
        return redirect(url_for("plans.plan_detail", pk=done.id))            # nothing left: back to the plan to give it out
    return redirect(url_for("review.detail", pk=pk))
