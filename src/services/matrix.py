"""Role Requirement Matrix: build a draft from the current requirements, then approve it.

The matrix is the independent ground truth that Pipeline 2 validates generated plans against.
It is built deterministically and becomes authoritative only after a person approves it.
"""
from collections import Counter

from sqlalchemy import func, select

from database import audit, db, utcnow
from database.models import Chunk, Conflict, Document, JobRole, MatrixRow, MatrixVersion, Requirement
from role_matrix.applicability import resolve_roles
from src.services.conflicts import detect_and_store, losing_requirement_ids
from src.services.requirements import link_requirements

POLICY_CATEGORIES = {"Policy", "Compliance", "Handbook", "FAQ", "Informal Guidance"}
SOURCE_STATUSES = ("active", "expired")


def build_draft(actor):
    """Create a new draft matrix version from all current, non-rejected requirements."""
    link_requirements()
    detect_and_store(actor)
    losers = losing_requirement_ids()
    conflict_of = {}
    for c in db.session.scalars(select(Conflict).where(Conflict.kind == "cross_document")):
        if c.status in ("manual_review", "auto_resolved_warning"):
            conflict_of[c.left_requirement_id] = conflict_of[c.right_requirement_id] = c.id
    roles = db.session.scalars(select(JobRole).where(JobRole.status == "active").order_by(JobRole.code)).all()
    rows_in = db.session.execute(
        select(Requirement, Document, Chunk)
        .join(Document, Requirement.document_id == Document.id)
        .join(Chunk, Requirement.chunk_id == Chunk.id)
        .where(Document.status.in_(SOURCE_STATUSES), Document.tier > 0,
               Requirement.review_status != "rejected", Chunk.quarantined.is_(False))
        .order_by(Requirement.doc_id, Requirement.position)).all()

    number = (db.session.scalar(select(func.max(MatrixVersion.version_no))) or 0) + 1
    version = MatrixVersion(version_no=number, status="draft", created_by=(actor or {}).get("email", "system"),
                            source_documents=sorted({(d.doc_id, d.version) for _, d, _ in rows_in}))
    by_code = {r.code: r for r in roles}
    per_role, mandatory, role_specific, rows = Counter(), 0, 0, []
    excluded = 0
    for req, doc, chunk in rows_in:
        if req.id in losers:
            excluded += 1                      # overridden by a higher-precedence rule
            continue
        codes = req.roles if req.review_status == "edited" else resolve_roles(
            req.subject, chunk.heading_path, doc.applies_to_text, roles)
        targets = list(by_code) if codes == ["ALL"] else [c for c in codes if c in by_code]
        role_specific += codes != ["ALL"]
        mandatory += req.mandatory
        for code in targets:
            per_role[code] += 1
            rows.append(MatrixRow(
                matrix_version=version, job_role_id=by_code[code].id, requirement_id=req.id,
                requirement_kind="policy" if doc.category in POLICY_CATEGORIES else "process",
                competency=req.competency, mandatory=req.mandatory, priority=req.priority, due_stage=req.due_stage,
                assessment_requirement=req.assessment_type, condition=req.condition, source_status=doc.status,
                conflict_id=conflict_of.get(req.id)))
    version.stats = {"requirements": len(rows_in) - excluded, "excluded_by_precedence": excluded, "rows": len(rows), "mandatory_requirements": mandatory,
                     "role_specific_requirements": role_specific, "per_role": dict(sorted(per_role.items()))}
    db.session.add(version)
    db.session.add_all(rows)
    audit.record("matrix.built", "matrix", number, actor=actor, after=version.stats, commit=False)
    db.session.commit()
    return version


def approve(version_no, actor):
    version = db.session.scalar(select(MatrixVersion).where(MatrixVersion.version_no == version_no))
    if version is None or version.status != "draft":
        raise ValueError("Only a draft matrix can be approved.")
    for old in db.session.scalars(select(MatrixVersion).where(MatrixVersion.status == "approved")):
        old.status = "retired"
    version.status, version.approved_by, version.approved_at = "approved", (actor or {}).get("email"), utcnow()
    audit.record("matrix.approved", "matrix", version_no, actor=actor, after={"status": "approved"}, commit=False)
    db.session.commit()
    return version
