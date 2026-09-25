"""Ground-truth pages: requirements (review and edit), the Role Requirement Matrix, security findings."""
from collections import Counter, defaultdict

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from sqlalchemy.orm import selectinload
from sqlalchemy import func, or_, select
from wtforms import SelectField, SelectMultipleField, StringField
from wtforms.validators import DataRequired

from config.loader import load_config
from database import audit, db, utcnow
from database.models import (REQ_TYPES, Chunk, Document, JobRole, MatrixRow, MatrixVersion, Requirement,
                             RequirementPrerequisite, SecurityFinding)
from src.rbac import require_permission
from src.services import matrix as matrix_service

bp = Blueprint("ground_truth", __name__)
PAGE_SIZE = 50


def _stage_choices():
    return [(s["code"], s["label"]) for s in load_config("stages")["stages"]]


# --------------------------------------------------------------------------- requirements

@bp.route("/requirements")
@require_permission("requirements.view")
def requirements():
    args = request.args
    query = (select(Requirement, Document).join(Document, Requirement.document_id == Document.id)
             .where(Document.status.in_(["active", "expired"])).options(selectinload(Requirement.chunk)))
    if args.get("doc"):
        query = query.where(Requirement.doc_id == args["doc"])
    if args.get("type"):
        query = query.where(Requirement.req_type == args["type"])
    if args.get("mandatory") in ("yes", "no"):
        query = query.where(Requirement.mandatory.is_(args["mandatory"] == "yes"))
    if args.get("review"):
        query = query.where(Requirement.review_status == args["review"])
    if args.get("q"):
        like = f"%{args['q'].strip()}%"
        query = query.where(or_(Requirement.text.ilike(like), Requirement.req_id.ilike(like)))
    rows = db.session.execute(query.order_by(Requirement.doc_id, Requirement.position)).all()
    if args.get("role"):
        rows = [(r, d) for r, d in rows if r.roles == ["ALL"] or args["role"] in r.roles]
    page = max(int(args.get("page", 1) or 1), 1)
    total = len(rows)
    docs = db.session.scalars(select(Document.doc_id).where(Document.status.in_(["active", "expired"]),
                                                            Document.tier > 0).distinct().order_by(Document.doc_id)).all()
    roles = db.session.scalars(select(JobRole).order_by(JobRole.code)).all()
    return render_template("ground_truth/requirements.html", rows=rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE],
                           total=total, page=page, pages=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1), args=args,
                           docs=docs, roles=roles, types=REQ_TYPES)


class RequirementForm(FlaskForm):
    req_type = SelectField("Requirement type", choices=[(t, t) for t in REQ_TYPES])
    roles = SelectMultipleField("Applies to roles")
    due_stage = SelectField("Due stage")
    priority = SelectField("Priority", choices=[(p, p) for p in ("High", "Medium", "Low")])
    competency = StringField("Competency", validators=[DataRequired()])
    decision = SelectField("Review decision", choices=[("confirmed", "Confirm"), ("edited", "Save my changes"),
                                                       ("rejected", "Reject: not a requirement")])
    reason = StringField("Reason (recorded in the audit trail)", validators=[DataRequired()])


EDITABLE = ("req_type", "mandatory", "roles", "due_stage", "priority", "competency", "review_status")


@bp.route("/requirements/<int:pk>", methods=["GET", "POST"])
@require_permission("requirements.view")
def requirement_detail(pk):
    req = db.session.get(Requirement, pk) or abort(404)
    roles = db.session.scalars(select(JobRole).order_by(JobRole.code)).all()
    form = RequirementForm(obj=req)
    form.roles.choices = [("ALL", "All roles")] + [(r.code, f"{r.code} · {r.name}") for r in roles]
    form.due_stage.choices = _stage_choices()
    if request.method == "GET":
        form.roles.data = req.roles
    if form.validate_on_submit():
        from src.rbac import has_permission
        if not has_permission(current_user, "requirements.edit"):
            abort(403)
        before = {k: getattr(req, k) for k in EDITABLE}
        if form.decision.data != "confirmed":
            req.req_type = form.req_type.data
            req.mandatory = req.req_type.startswith("Must")
            req.roles = ["ALL"] if "ALL" in form.roles.data or not form.roles.data else form.roles.data
            req.due_stage, req.priority = form.due_stage.data, form.priority.data
            req.competency = form.competency.data.strip()
        req.review_status = form.decision.data
        req.reviewed_by, req.reviewed_at = current_user.email, utcnow()
        after = {k: getattr(req, k) for k in EDITABLE}
        audit.record(f"requirement.{form.decision.data}", "requirement", req.req_id, version=req.version,
                     actor=audit.actor_from_user(current_user), before=before, after=after,
                     reason=form.reason.data, commit=False)
        db.session.commit()
        changed = [k for k in EDITABLE if k != "review_status" and before[k] != after[k]]
        rebuild = bool(changed) or "rejected" in (before["review_status"], after["review_status"])
        flash(f"{req.req_id} was {form.decision.data}. " + (
            "Build a new matrix draft to include the change." if rebuild
            else "No values changed; the matrix does not need rebuilding."), "success")
        return redirect(url_for("ground_truth.requirement_detail", pk=req.id))
    prereqs = db.session.execute(
        select(Requirement, RequirementPrerequisite.source)
        .join(RequirementPrerequisite, RequirementPrerequisite.prerequisite_id == Requirement.id)
        .where(RequirementPrerequisite.requirement_id == req.id)).all()
    history = db.session.scalars(select(Requirement).where(Requirement.req_id == req.req_id)
                                 .order_by(Requirement.created_at)).all()
    return render_template("ground_truth/requirement_detail.html", req=req, form=form, prereqs=prereqs,
                           history=history)


# --------------------------------------------------------------------------- matrix

@bp.route("/matrix")
@require_permission("matrix.view")
def matrix_index():
    versions = db.session.scalars(select(MatrixVersion).order_by(MatrixVersion.version_no.desc())).all()
    return render_template("ground_truth/matrix_index.html", versions=versions)


@bp.route("/matrix/build", methods=["POST"])
@require_permission("matrix.build")
def matrix_build():
    version = matrix_service.build_draft(audit.actor_from_user(current_user))
    flash(f"Draft matrix v{version.version_no} built: {version.stats['rows']} rows from "
          f"{version.stats['requirements']} requirements. Review it, then approve.", "success")
    return redirect(url_for("ground_truth.matrix_view", number=version.version_no))


@bp.route("/matrix/<int:number>/approve", methods=["POST"])
@require_permission("matrix.approve")
def matrix_approve(number):
    try:
        matrix_service.approve(number, audit.actor_from_user(current_user))
        flash(f"Matrix v{number} is now the approved ground truth.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("ground_truth.matrix_view", number=number))


@bp.route("/matrix/<int:number>")
@require_permission("matrix.view")
def matrix_view(number):
    version = db.session.scalar(select(MatrixVersion).where(MatrixVersion.version_no == number)) or abort(404)
    roles = db.session.scalars(select(JobRole).order_by(JobRole.code)).all()
    role_code = request.args.get("role") or (roles[0].code if roles else "")
    role = next((r for r in roles if r.code == role_code), None)
    summary = defaultdict(Counter)
    for code, mandatory, stage in db.session.execute(
            select(JobRole.code, MatrixRow.mandatory, MatrixRow.due_stage).join(JobRole)
            .where(MatrixRow.matrix_version_id == version.id)):
        summary[code]["total"] += 1
        summary[code]["mandatory" if mandatory else "optional"] += 1
    rows = db.session.execute(
        select(MatrixRow, Requirement).join(Requirement, MatrixRow.requirement_id == Requirement.id)
        .where(MatrixRow.matrix_version_id == version.id, MatrixRow.job_role_id == (role.id if role else -1))
        .order_by(MatrixRow.mandatory.desc(), Requirement.doc_id, Requirement.position)).all()
    stage_order = {s["code"]: i for i, s in enumerate(load_config("stages")["stages"])}
    rows.sort(key=lambda r: (not r[0].mandatory, stage_order.get(r[0].due_stage, 99)))
    return render_template("ground_truth/matrix_view.html", version=version, roles=roles, role=role,
                           summary=summary, rows=rows)


# --------------------------------------------------------------------------- conflicts

@bp.route("/conflicts")
@require_permission("conflicts.view")
def conflicts():
    from database.models import Conflict
    rows = db.session.scalars(select(Conflict).options(
        *[selectinload(rel).selectinload(Requirement.document) for rel in (Conflict.left, Conflict.right)],
        selectinload(Conflict.winner))).all()
    order = {"manual_review": 0, "auto_resolved_warning": 1, "resolved_by_reviewer": 2, "auto_resolved": 3}
    rows.sort(key=lambda c: (c.kind != "cross_document", order.get(c.status, 9), c.conflict_code))
    counts = Counter(c.status for c in rows if c.kind == "cross_document")
    return render_template("ground_truth/conflicts.html", rows=rows, counts=counts,
                           versions=sum(c.kind == "version" for c in rows))


@bp.route("/conflicts/detect", methods=["POST"])
@require_permission("conflicts.detect")
def conflicts_detect():
    from src.services.conflicts import detect_and_store
    found = detect_and_store(audit.actor_from_user(current_user))
    db.session.commit()
    flash(f"Contradiction check complete: {len(found)} conflict(s) found and resolved by the precedence rules.", "success")
    return redirect(url_for("ground_truth.conflicts"))


@bp.route("/conflicts/<int:pk>/resolve", methods=["POST"])
@require_permission("conflicts.resolve")
def conflict_resolve(pk):
    from database.models import Conflict
    from src.services.conflicts import resolve_by_reviewer
    conflict = db.session.get(Conflict, pk) or abort(404)
    side, reason = request.form.get("winner"), (request.form.get("reason") or "").strip()
    if side not in ("left", "right") or not reason:
        flash("Choose which rule applies and give a reason; both are recorded in the audit trail.", "error")
    else:
        resolve_by_reviewer(conflict, side, reason, audit.actor_from_user(current_user))
        flash(f"{conflict.conflict_code} resolved. Build a new matrix draft to apply the decision.", "success")
    return redirect(url_for("ground_truth.conflicts") + f"#{conflict.conflict_code}")


# --------------------------------------------------------------------------- security

@bp.route("/security")
@require_permission("security.view")
def security():
    rows = db.session.execute(
        select(SecurityFinding, Document, Chunk).join(Document, SecurityFinding.document_id == Document.id)
        .outerjoin(Chunk, SecurityFinding.chunk_id == Chunk.id)
        .order_by(Document.doc_id, Document.version)).all()
    counts = Counter(f.technique for f, _, _ in rows)
    quarantined = db.session.scalar(select(func.count()).select_from(Chunk).where(Chunk.quarantined))
    return render_template("ground_truth/security.html", rows=rows, counts=counts, quarantined=quarantined)


@bp.route("/topics")
@require_permission("requirements.view")
def topic_check():
    """Would the approved documents support training on this topic? Python decides; no GenAI call is made."""
    from hallucination_checks import assess
    topic = " ".join((request.args.get("topic") or "").split())[:200]
    result = None
    if topic:
        cfg = load_config("hallucination")
        chunks = db.session.execute(select(Chunk.id, Chunk.chunk_id, Chunk.doc_id, Chunk.section_id, Chunk.heading, Chunk.text)
                                    .where(Chunk.doc_status == "active", Chunk.quarantined.is_(False))).all()
        req_ids = defaultdict(list)
        for chunk_pk, req_id in db.session.execute(select(Requirement.chunk_id, Requirement.req_id)
                                                   .join(Document, Requirement.document_id == Document.id)
                                                   .where(Document.status == "active")):
            req_ids[chunk_pk].append(req_id)
        passages = [{"ref": cid, "doc_id": doc, "section_id": sec, "text": f"{heading} {text}",
                     "requirements": req_ids.get(pk, [])} for pk, cid, doc, sec, heading, text in chunks]
        result = assess(topic, passages, supported_at=cfg["supported_at"], review_at=cfg["review_at"],
                        max_matches=cfg["max_matches"], extra_stopwords=cfg.get("extra_stopwords", []))
        if current_user.app_role != "demo":
            audit.record(f"topic.{result.status}", "topic", topic[:120], actor=audit.actor_from_user(current_user),
                         detail={"score": result.score, "sources": [m["ref"] for m in result.matches]})
    return render_template("ground_truth/topic_check.html", topic=topic, result=result, thresholds=load_config("hallucination"))
