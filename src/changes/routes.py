"""Policy changes: what changed between versions, what it affects, selective regeneration (SRS Steps 57-59)."""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import audit, db
from database.models import ChangeImpact
from genai_pipeline.providers import ProviderError
from src.rbac import require_permission
from src.services import changes

bp = Blueprint("changes", __name__)


@bp.route("/changes")
@require_permission("documents.view")
def index():
    upcoming = db.session.scalars(select(ChangeImpact).where(ChangeImpact.status == "upcoming")).all()
    for c in upcoming:                              # a scheduled version may have come into force
        changes.refresh_status(c)
    if upcoming:
        db.session.commit()
    rows = db.session.scalars(select(ChangeImpact).options(selectinload(ChangeImpact.to_document))
                              .order_by(ChangeImpact.created_at.desc(), ChangeImpact.id.desc())).all()
    return render_template("changes/index.html", rows=rows, impacts=changes.impact_counts(rows))


@bp.route("/changes/detect", methods=["POST"])
@require_permission("documents.upload")
def detect():
    created = changes.detect_changes(actor=audit.actor_from_user(current_user))
    db.session.commit()
    flash(f"{len(created)} new policy change(s) recorded." if created else "No new document versions to compare.", "success")
    return redirect(url_for("changes.index"))


@bp.route("/changes/<int:pk>")
@require_permission("documents.view")
def detail(pk):
    c = db.session.get(ChangeImpact, pk) or abort(404)
    changes.refresh_status(c)
    db.session.commit()
    diffs = {x["req_id"]: changes.word_diff(x["old_text"], x["new_text"]) for x in c.changes if x["change"] == "changed"}
    return render_template("changes/detail.html", c=c, info=changes.impact(c), diffs=diffs,
                           blockers=changes.regeneration_blockers(c))


@bp.route("/changes/<int:pk>/regenerate", methods=["POST"])
@require_permission("plans.generate")
def regenerate(pk):
    c = db.session.get(ChangeImpact, pk) or abort(404)
    plan_ids = [int(x) for x in request.form.getlist("plan_id")] or None
    try:
        results = changes.regenerate_for_change(c, audit.actor_from_user(current_user), current_app.config, plan_ids)
    except changes.ChangeError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("changes.detail", pk=pk))
    except (ProviderError, ValueError) as exc:
        db.session.rollback()
        flash(f"Regeneration did not run: {exc}", "error")
        return redirect(url_for("changes.detail", pk=pk))
    flash("Regenerated only the affected modules: " + "; ".join(
        f"{a.plan_code} v{a.version} -> v{b.version} ({b.status})" for a, b in results), "success")
    return redirect(url_for("changes.detail", pk=pk))
