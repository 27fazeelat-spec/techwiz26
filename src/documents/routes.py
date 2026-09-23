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
from database.models import Document, DocumentFile, Requirement, SecurityFinding
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
    return render_template("documents/index.html", docs=docs, status=status, category=category, q=q,
                           categories=load_config("documents")["categories"], statuses=STATUSES)


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
            flash(f"{result.doc.doc_id} version {result.doc.version} was ingested and is {result.doc.status}.",
                  "success")
            return redirect(url_for("documents.detail", doc_id=result.doc.doc_id, version=result.doc.version))
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
    return render_template("documents/detail.html", doc=doc, lineage=lineage, chunks=doc.chunks,
                           findings=findings, req_counts=req_counts)


@bp.route("/<doc_id>/<version>/file")
@require_permission("documents.view")
def download(doc_id, version):
    doc = _get_or_404(doc_id, version)
    stored = db.session.scalar(select(DocumentFile).options(undefer(DocumentFile.content))
                               .where(DocumentFile.id == doc.file_id))
    mimetype = ("application/pdf" if stored.format == "pdf" else
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return send_file(io.BytesIO(stored.content), download_name=stored.filename, as_attachment=True, mimetype=mimetype)
