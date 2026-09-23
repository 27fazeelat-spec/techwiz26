"""Detect contradictions among current requirements, resolve them by precedence, and store the results.

Reviewer decisions survive re-detection: a conflict is identified by its requirement pair, and a pair a
reviewer has resolved keeps that decision.
"""
from sqlalchemy import select

from contradiction_checks import detect, resolve
from database import audit, db, utcnow
from database.models import Conflict, Document, Requirement

RESOLVED = ("auto_resolved", "auto_resolved_warning", "resolved_by_reviewer")


def _as_dict(req, doc):
    strength = "mandatory" if req.mandatory else ("recommended" if req.req_type == "Recommended" else "optional")
    return {"id": req.id, "req_id": req.req_id, "doc_id": req.doc_id, "version": req.version, "tier": doc.tier,
            "category": doc.category, "text": req.text, "strength": strength, "section_id": req.section_id}


def _pair_key(kind, a, b):
    ends = sorted([f"{a['req_id']}@{a['version']}", f"{b['req_id']}@{b['version']}"])
    return f"{kind}:{'|'.join(ends)}"


def detect_and_store(actor=None):
    rows = db.session.execute(select(Requirement, Document).join(Document, Requirement.document_id == Document.id)
                              .where(Requirement.review_status != "rejected")).all()
    current = [_as_dict(r, d) for r, d in rows if d.status in ("active", "expired") and not r.chunk.quarantined]
    by_req = {c["req_id"]: c for c in current}
    previous = []
    for r, d in rows:
        if d.status == "superseded" and r.req_id in by_req:
            previous.append({**_as_dict(r, d), "current_id": by_req[r.req_id]["id"]})

    found = detect(current, previous)
    existing = {c.pair_key: c for c in db.session.scalars(select(Conflict))}
    keep = set()
    number = max([int(c.conflict_code.split("-")[1]) for c in existing.values()] or [0])
    for item in found:
        key = _pair_key(item["kind"], item["left"], item["right"])
        keep.add(key)
        previous_row = existing.get(key)
        if previous_row is not None and previous_row.status == "resolved_by_reviewer":
            continue
        verdict = resolve(item)
        winner = item[verdict["winner"]]["id"] if verdict["winner"] else None
        if previous_row is None:
            number += 1
            previous_row = Conflict(conflict_code=f"CF-{number:04d}", kind=item["kind"], pair_key=key)
            db.session.add(previous_row)
        previous_row.left_requirement_id, previous_row.right_requirement_id = item["left"]["id"], item["right"]["id"]
        previous_row.differences, previous_row.similarity = item["differences"], item["similarity"]
        previous_row.rule_applied, previous_row.winner_requirement_id = verdict["rule"], winner
        previous_row.explanation, previous_row.status = verdict["explanation"], verdict["status"]
    stale = [c for k, c in existing.items() if k not in keep and c.status != "resolved_by_reviewer"]
    for c in stale:
        db.session.delete(c)
    db.session.flush()
    audit.record("conflicts.detected", "conflicts", "all", actor=actor,
                 after={"found": len(found), "removed_stale": len(stale)}, commit=False)
    return found


def current_conflicts():
    """Conflicts whose both sides are still current requirements."""
    rows = db.session.scalars(select(Conflict)).all()
    return [c for c in rows if c.left.document.status in ("active", "expired") or c.kind == "version"]


def losing_requirement_ids():
    """Requirement row ids that lost a resolved conflict: excluded from the matrix and from Gemini's sources."""
    ids = set()
    for c in db.session.scalars(select(Conflict).where(Conflict.status.in_(RESOLVED), Conflict.kind == "cross_document")):
        if c.winner_requirement_id is not None:
            ids.add(c.right_requirement_id if c.winner_requirement_id == c.left_requirement_id else c.left_requirement_id)
    return ids


def resolve_by_reviewer(conflict, winner_side, reason, actor):
    """winner_side: 'left' | 'right'."""
    before = {"status": conflict.status, "winner": conflict.winner.req_id if conflict.winner else None}
    conflict.winner_requirement_id = conflict.left_requirement_id if winner_side == "left" else conflict.right_requirement_id
    conflict.status, conflict.rule_applied = "resolved_by_reviewer", "reviewer"
    conflict.reviewed_by, conflict.reviewed_at, conflict.review_reason = (actor or {}).get("email"), utcnow(), reason
    conflict.explanation = f"Resolved by {conflict.reviewed_by}: {reason}"
    winner = db.session.get(Requirement, conflict.winner_requirement_id)
    audit.record("conflict.resolved", "conflict", conflict.conflict_code, actor=actor, before=before,
                 after={"status": conflict.status, "winner": winner.req_id}, reason=reason, commit=False)
    db.session.commit()
