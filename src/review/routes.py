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
    rows = db.session.execute(query).all()
    return render_template("review/queue.html", rows=rows, show=show, counts=review.queue_counts())


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
    return render_template("review/detail.html", r=r, item=item, sources=sources, history=history,
                           fields=review.editable_fields(item) if item else [],
                           override_statuses=review.cfg()["override_statuses"], code=review.code(r),
                           state=review.plan_review_state(r.plan))


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
    if action != "comment" and nxt is not None and request.form.get("then") == "next":
        return redirect(url_for("review.detail", pk=nxt.id))
    return redirect(url_for("review.detail", pk=pk))
