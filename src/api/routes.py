"""Small JSON endpoints used by the interface (hover cards). Read-only."""
import time

from flask import Blueprint, abort, current_app, jsonify
from flask_login import current_user, login_required
from sqlalchemy import select

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
    cache = current_app.extensions.setdefault("ref_docs", {"at": 0, "ids": []})
    if time.time() - cache["at"] > 300:
        cache["ids"] = sorted(set(db.session.scalars(select(Document.doc_id))))
        cache["at"] = time.time()
    return cache["ids"]
