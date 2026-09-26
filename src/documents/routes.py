import io

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from sqlalchemy import func, or_, select
from sqlalchemy.orm import undefer
from wtforms import DateField, SelectField, StringField
from wtforms.validators import Optional

from config.loader import load_config
from config.settings import today
from database import audit, db
from database.models import Document, DocumentFile, JobRole, Requirement, SecurityFinding
from document_processing.metadata import version_key
from src.rbac import require_permission
from src.services.ingestion import ingest_document

bp = Blueprint("documents", __name__, url_prefix="/documents")
STATUSES = ["active", "scheduled", "superseded", "expired", "draft"]


class UploadForm(FlaskForm):
    file = FileField("Document (PDF or DOCX)", validators=[FileRequired()])
    doc_id = StringField("Document ID", validators=[Optional()])
    version = StringField("Version", validators=[Optional()])
    title = StringField("Title", validators=[Optional()])
    category = SelectField("Category", validators=[Optional()])
    owner_department = SelectField("Owner department", validators=[Optional()])
    applies_to = StringField("Applies to", validators=[Optional()])
    effective_date = DateField("Effective date", validators=[Optional()])
    expiry_date = DateField("Review / expiry date", validators=[Optional()])


def _form():
    rules = load_config("documents")
    form = UploadForm()
    form.category.choices = [("", "Read from document")] + [(c, c) for c in rules["categories"]]
    form.owner_department.choices = [("", "Read from document")] + [(d, d) for d in rules["departments"]]
    return form


def _get_or_404(doc_id, version):
    doc = db.session.scalar(select(Document).where(Document.doc_id == doc_id, Document.version == version))
    if doc is None:
        abort(404)
    return doc


# Plain words for a version's status, and the order the status chart draws them in.
PLAIN_STATUS = {"active": "In force", "scheduled": "Coming soon", "draft": "Draft", "expired": "Expired",
                "superseded": "Older version"}


def _rule_counts():
    """{document row id: (rules, set of role codes)} for every version."""
    counts = {}
    for document_id, roles in db.session.execute(select(Requirement.document_id, Requirement.roles)):
        n, codes = counts.get(document_id, (0, set()))
        counts[document_id] = (n + 1, codes | set(roles or []))
    return counts


def _jobs_label(codes):
    if not codes:
        return "No job named"
    if "ALL" in codes:
        return "Everyone"
    return f"{len(codes)} job{'s' if len(codes) != 1 else ''}"


def _library(docs):
    """One card per document (all versions of a doc_id), showing the version in force, else the newest."""
    counts = _rule_counts()
    flagged = set(db.session.scalars(select(SecurityFinding.document_id).distinct()))
    lineages = {}
    for d in docs:
        lineages.setdefault(d.doc_id, []).append(d)
    cards = []
    for doc_id, versions in lineages.items():
        versions.sort(key=lambda d: version_key(d.version), reverse=True)
        current = next((d for d in versions if d.status == "active"), versions[0])
        rules, codes = counts.get(current.id, (0, set()))
        cards.append({"doc": current, "versions": versions, "rules": rules, "jobs": _jobs_label(codes),
                      "department": current.owner_department or "Other",
                      "flag": any(v.id in flagged or (v.parse or {}).get("hidden_blocks") for v in versions)})
    cards.sort(key=lambda c: (c["department"], c["doc"].title or c["doc"].doc_id))
    return cards


@bp.route("/")
@require_permission("documents.view")
def index():
    status = request.args.get("status", "")
    category = request.args.get("category", "")
    q = request.args.get("q", "").strip()
    query = select(Document)
    if status:
        query = query.where(Document.status == status)
    if category:
        query = query.where(Document.category == category)
    if q:
        like = f"%{q}%"
        query = query.where(or_(Document.doc_id.ilike(like), Document.title.ilike(like)))
    docs = db.session.scalars(query).all()
    docs.sort(key=lambda d: (d.doc_id, [-n for n in version_key(d.version)]))
    cards = _library(docs)
    by_status = [(s, PLAIN_STATUS[s], sum(1 for d in docs if d.status == s))
                 for s in ("active", "scheduled", "draft", "expired", "superseded")]
    departments = {}
    for c in cards:
        departments[c["department"]] = departments.get(c["department"], 0) + 1
    return render_template("documents/index.html", docs=docs, cards=cards, status=status, category=category, q=q,
                           categories=load_config("documents")["categories"], statuses=STATUSES,
                           by_status=[s for s in by_status if s[2]], plain_status=PLAIN_STATUS,
                           donut=[{"key": k, "label": label, "value": n} for k, label, n in by_status if n],
                           departments=sorted(departments.items(), key=lambda kv: (-kv[1], kv[0])),
                           total_rules=sum(c["rules"] for c in cards),
                           need_look=sum(1 for c in cards if c["flag"] or c["doc"].status != "active"))


@bp.route("/upload", methods=["GET", "POST"])
@require_permission("documents.upload")
def upload():
    form = _form()
    if form.validate_on_submit():
        file = form.file.data
        manual = {name: getattr(form, name).data for name in
                  ("doc_id", "version", "title", "category", "owner_department", "applies_to",
                   "effective_date", "expiry_date")}
        result = ingest_document(file.read(), file.filename, form=manual,
                                 actor=audit.actor_from_user(current_user), today=today(current_app.config))
        if result.ok:
            return redirect(url_for("documents.detail", doc_id=result.doc.doc_id, version=result.doc.version,
                                    uploaded=1))
        return render_template("documents/upload.html", form=form, result=result), 422
    return render_template("documents/upload.html", form=form, result=None)


@bp.route("/<doc_id>/<version>")
@require_permission("documents.view")
def detail(doc_id, version):
    doc = _get_or_404(doc_id, version)
    lineage = db.session.scalars(select(Document).where(Document.doc_id == doc_id)).all()
    lineage.sort(key=lambda d: version_key(d.version), reverse=True)
    findings = db.session.scalars(select(SecurityFinding).where(SecurityFinding.document_id == doc.id)).all()
    req_counts = dict(db.session.execute(select(Requirement.chunk_id, func.count()).where(
        Requirement.document_id == doc.id).group_by(Requirement.chunk_id)).all())
    rules = db.session.scalars(select(Requirement).where(Requirement.document_id == doc.id)
                               .order_by(Requirement.position)).all()
    codes = {code for r in rules for code in (r.roles or [])}
    names = dict(db.session.execute(select(JobRole.code, JobRole.name)).all())
    jobs = ["Everyone"] if "ALL" in codes else sorted(names.get(c, c) for c in codes)
    # What each version changed compared with the one before it, oldest first for the timeline.
    changes = {}
    for document_id, change, n in db.session.execute(
            select(Requirement.document_id, Requirement.lineage_change, func.count())
            .where(Requirement.document_id.in_([v.id for v in lineage]))
            .group_by(Requirement.document_id, Requirement.lineage_change)):
        changes.setdefault(document_id, {})[change] = n
    timeline, before = [], None
    for v in reversed(lineage):
        c = changes.get(v.id, {})
        kept = c.get("changed", 0) + c.get("unchanged", 0)
        timeline.append({"doc": v, "total": kept + c.get("added", 0), "first": before is None,
                         "added": c.get("added", 0), "changed": c.get("changed", 0),
                         "removed": max(0, before - kept) if before is not None else 0})
        before = kept + c.get("added", 0)
    return render_template("documents/detail.html", doc=doc, lineage=lineage, chunks=doc.chunks,
                           findings=findings, req_counts=req_counts, rules=rules, jobs=jobs, timeline=timeline,
                           plain_status=PLAIN_STATUS, just_uploaded=request.args.get("uploaded") == "1")


@bp.route("/<doc_id>/<version>/file")
@require_permission("documents.view")
def download(doc_id, version):
    doc = _get_or_404(doc_id, version)
    stored = db.session.scalar(select(DocumentFile).options(undefer(DocumentFile.content))
                               .where(DocumentFile.id == doc.file_id))
    mimetype = ("application/pdf" if stored.format == "pdf" else
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return send_file(io.BytesIO(stored.content), download_name=stored.filename, as_attachment=True, mimetype=mimetype)
