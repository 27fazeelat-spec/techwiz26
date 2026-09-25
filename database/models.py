"""Relational schema (documentation/03_Database_Design.md).

Tables built so far: organisation and people, documents and chunks, audit log.
JSON columns become JSONB on PostgreSQL; they hold values that are always read as a whole
(metadata sources, parse statistics, heading paths) and never need to be joined on.
"""
from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
                        LargeBinary, String, Text, UniqueConstraint, event)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from database import db, utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")

APP_ROLES = ("admin", "training_manager", "reviewer", "manager", "employee")
DOC_STATUSES = ("pending", "active", "superseded", "scheduled", "expired", "draft")


def _in(column, values):
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


# --------------------------------------------------------------------------- organisation and people

class Organization(db.Model):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)


class Property(db.Model):
    __tablename__ = "properties"
    __table_args__ = (UniqueConstraint("organization_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(40))
    services: Mapped[dict] = mapped_column(JSONType, default=dict)


class JobRole(db.Model):
    __tablename__ = "job_roles"
    __table_args__ = (UniqueConstraint("organization_id", "code"),
                      CheckConstraint(_in("status", ("active", "pending_mapping")), name="ck_job_roles_status"))
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(120))
    department: Mapped[str] = mapped_column(String(120))
    aliases: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("app_role", APP_ROLES), name="ck_users_app_role"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(100))
    app_role: Mapped[str] = mapped_column(String(20))
    employee_code: Mapped[str | None] = mapped_column(String(20), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Employee(db.Model):
    __tablename__ = "employees"
    __table_args__ = (CheckConstraint(_in("experience_level", ("Beginner", "Intermediate", "Advanced")),
                                      name="ck_employees_experience_level"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    employee_code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    job_role_id: Mapped[int] = mapped_column(ForeignKey("job_roles.id"), index=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    department: Mapped[str] = mapped_column(String(120))
    experience_level: Mapped[str] = mapped_column(String(20))
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    previous_experience: Mapped[str | None] = mapped_column(String(300))
    joining_date: Mapped[date] = mapped_column(Date)
    reporting_manager_code: Mapped[str | None] = mapped_column(String(20), index=True)
    certifications: Mapped[list] = mapped_column(JSONType, default=list)
    assignments: Mapped[list] = mapped_column(JSONType, default=list)
    shift_pattern: Mapped[str] = mapped_column(String(20), default="day")
    training_status: Mapped[str] = mapped_column(String(20), default="not_started")
    left_on: Mapped[date | None] = mapped_column(Date)                # set when the person leaves; the record stays
    left_reason: Mapped[str | None] = mapped_column(String(300))

    @property                                  # defined before the "property" relationship below, which shadows the name
    def has_left(self):
        return self.left_on is not None

    job_role: Mapped[JobRole] = relationship()
    property: Mapped[Property] = relationship()


# --------------------------------------------------------------------------- knowledge base

class DocumentFile(db.Model):
    """The original uploaded file. Stored in the database because container disks are ephemeral."""
    __tablename__ = "document_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    format: Mapped[str] = mapped_column(String(10))
    content: Mapped[bytes] = deferred(mapped_column(LargeBinary))   # loaded only when downloaded


class Document(db.Model):
    """One row per document version. doc_id is the lineage key shared by all versions."""
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("doc_id", "version"),
                      CheckConstraint(_in("status", DOC_STATUSES), name="ck_documents_status"),
                      Index("ix_documents_status_category", "status", "category"))
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(30), index=True)
    version: Mapped[str] = mapped_column(String(20))
    title: Mapped[str | None] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(40))
    tier: Mapped[int] = mapped_column(Integer, default=0)
    owner_department: Mapped[str | None] = mapped_column(String(120))
    applies_to_text: Mapped[str | None] = mapped_column(String(500))
    header_status: Mapped[str | None] = mapped_column(String(120))
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    effective_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    supersedes_text: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    superseded_by: Mapped[str | None] = mapped_column(String(20))
    file_id: Mapped[int] = mapped_column(ForeignKey("document_files.id"))
    metadata_source: Mapped[dict] = mapped_column(JSONType, default=dict)
    parse: Mapped[dict] = mapped_column(JSONType, default=dict)
    warnings: Mapped[list] = mapped_column(JSONType, default=list)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str] = mapped_column(String(254))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    file: Mapped[DocumentFile] = relationship()
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan",
                                                 order_by="Chunk.position")


class Chunk(db.Model):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_doc_version_position", "doc_id", "version", "position"),
                      Index("ix_chunks_source_filter", "doc_status", "quarantined"))
    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(120), unique=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    doc_id: Mapped[str] = mapped_column(String(30))          # denormalised for traceability queries
    version: Mapped[str] = mapped_column(String(20))
    section_id: Mapped[str] = mapped_column(String(60))
    heading: Mapped[str] = mapped_column(String(300), default="")
    heading_path: Mapped[list] = mapped_column(JSONType, default=list)
    text: Mapped[str] = mapped_column(Text)
    raw_text: Mapped[str] = mapped_column(Text)
    location: Mapped[dict] = mapped_column(JSONType, default=dict)
    position: Mapped[int] = mapped_column(Integer)
    word_count: Mapped[int] = mapped_column(Integer)
    hidden_content: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden_text: Mapped[str] = mapped_column(Text, default="")
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    doc_status: Mapped[str] = mapped_column(String(20), default="pending")

    document: Mapped[Document] = relationship(back_populates="chunks")

    @property
    def source_text(self):
        """Text that may be used as a source: hidden text is never part of it."""
        if self.hidden_text:
            hidden = " ".join(self.hidden_text.replace("​", "").split())
            return " ".join(" ".join(self.text.split()).replace(hidden, " ").split())
        return self.text


# --------------------------------------------------------------------------- security

class SecurityFinding(db.Model):
    __tablename__ = "security_findings"
    __table_args__ = (Index("ix_security_findings_document", "document_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"))
    technique: Mapped[str] = mapped_column(String(40))
    pattern: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(30))
    excerpt: Mapped[str] = mapped_column(Text)
    decoded: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    document: Mapped[Document] = relationship()
    chunk: Mapped["Chunk | None"] = relationship()


# --------------------------------------------------------------------------- ground truth

REQ_TYPES = ("Must Know", "Must Complete", "Must Demonstrate", "Must Acknowledge", "Recommended", "Optional",
             "Not Applicable")
REVIEW_STATUSES = ("pending", "confirmed", "edited", "rejected")


class Requirement(db.Model):
    """One requirement clause in one document version. req_id is stable across versions (lineage)."""
    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("document_id", "req_id"),
                      CheckConstraint(_in("req_type", REQ_TYPES), name="ck_requirements_type"),
                      CheckConstraint(_in("review_status", REVIEW_STATUSES), name="ck_requirements_review"),
                      Index("ix_requirements_req_id", "req_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    req_id: Mapped[str] = mapped_column(String(40))
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"))
    doc_id: Mapped[str] = mapped_column(String(30))
    version: Mapped[str] = mapped_column(String(20))
    section_id: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    req_type: Mapped[str] = mapped_column(String(20))
    mandatory: Mapped[bool] = mapped_column(Boolean)
    modality: Mapped[str] = mapped_column(String(80))
    roles: Mapped[list] = mapped_column(JSONType, default=list)
    subject: Mapped[str] = mapped_column(Text, default="")
    condition: Mapped[dict | None] = mapped_column(JSONType)
    due_stage: Mapped[str] = mapped_column(String(10))
    stage_source: Mapped[str] = mapped_column(String(20))        # text | default
    priority: Mapped[str] = mapped_column(String(10))
    competency: Mapped[str] = mapped_column(String(60))
    assessment_type: Mapped[str] = mapped_column(String(20))
    facts: Mapped[list] = mapped_column(JSONType, default=list)
    cross_refs: Mapped[list] = mapped_column(JSONType, default=list)
    lineage_change: Mapped[str] = mapped_column(String(10), default="added")
    previous_requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id", ondelete="SET NULL"))
    review_status: Mapped[str] = mapped_column(String(10), default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String(254))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    document: Mapped[Document] = relationship()
    chunk: Mapped[Chunk] = relationship()
    previous: Mapped["Requirement | None"] = relationship(remote_side="Requirement.id")


class RequirementPrerequisite(db.Model):
    __tablename__ = "requirement_prerequisites"
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True)
    prerequisite_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(30))      # training_reference | cross_reference


CONFLICT_STATUSES = ("auto_resolved", "auto_resolved_warning", "manual_review", "resolved_by_reviewer")


class Conflict(db.Model):
    """A contradiction between two requirements and how precedence resolved it (SRS Steps 33-34)."""
    __tablename__ = "conflicts"
    __table_args__ = (CheckConstraint(_in("status", CONFLICT_STATUSES), name="ck_conflicts_status"),
                      CheckConstraint(_in("kind", ("cross_document", "version")), name="ck_conflicts_kind"))
    id: Mapped[int] = mapped_column(primary_key=True)
    conflict_code: Mapped[str] = mapped_column(String(20), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    pair_key: Mapped[str] = mapped_column(String(200), index=True)          # stable identity across re-detection
    left_requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"))
    right_requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"))
    differences: Mapped[list] = mapped_column(JSONType, default=list)
    similarity: Mapped[float] = mapped_column()
    rule_applied: Mapped[str] = mapped_column(String(30))
    winner_requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id", ondelete="SET NULL"))
    explanation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30))
    reviewed_by: Mapped[str | None] = mapped_column(String(254))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    left: Mapped[Requirement] = relationship(foreign_keys=[left_requirement_id])
    right: Mapped[Requirement] = relationship(foreign_keys=[right_requirement_id])
    winner: Mapped["Requirement | None"] = relationship(foreign_keys=[winner_requirement_id])

    @property
    def loser(self):
        if self.winner_requirement_id is None:
            return None
        return self.right if self.winner_requirement_id == self.left_requirement_id else self.left


class MatrixVersion(db.Model):
    __tablename__ = "matrix_versions"
    __table_args__ = (CheckConstraint(_in("status", ("draft", "approved", "retired")), name="ck_matrix_status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    version_no: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(10), default="draft")
    source_documents: Mapped[list] = mapped_column(JSONType, default=list)
    stats: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_by: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    approved_by: Mapped[str | None] = mapped_column(String(254))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)

    rows: Mapped[list["MatrixRow"]] = relationship(back_populates="matrix_version", cascade="all, delete-orphan")


class MatrixRow(db.Model):
    """The Role Requirement Matrix (SRS Step 10): one row per role x requirement."""
    __tablename__ = "matrix_rows"
    __table_args__ = (UniqueConstraint("matrix_version_id", "job_role_id", "requirement_id"),
                      Index("ix_matrix_rows_role", "matrix_version_id", "job_role_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    matrix_version_id: Mapped[int] = mapped_column(ForeignKey("matrix_versions.id", ondelete="CASCADE"))
    job_role_id: Mapped[int] = mapped_column(ForeignKey("job_roles.id"))
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"))
    requirement_kind: Mapped[str] = mapped_column(String(10))    # policy | process
    competency: Mapped[str] = mapped_column(String(60))
    mandatory: Mapped[bool] = mapped_column(Boolean)
    priority: Mapped[str] = mapped_column(String(10))
    due_stage: Mapped[str] = mapped_column(String(10))
    assessment_requirement: Mapped[str] = mapped_column(String(20))
    condition: Mapped[dict | None] = mapped_column(JSONType)
    source_status: Mapped[str] = mapped_column(String(20))       # active | expired
    conflict_id: Mapped[int | None] = mapped_column(ForeignKey("conflicts.id", ondelete="SET NULL"))

    matrix_version: Mapped[MatrixVersion] = relationship(back_populates="rows")
    job_role: Mapped[JobRole] = relationship()
    requirement: Mapped[Requirement] = relationship()


# --------------------------------------------------------------------------- generation

PLAN_STATUSES = ("generating", "Verified", "Verified with Warning", "Incomplete", "Unsupported", "Contradictory",
                 "Manual Review Required", "Failed", "superseded")


class Plan(db.Model):
    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("plan_code", "version"),
                      CheckConstraint(_in("status", PLAN_STATUSES), name="ck_plans_status"),
                      Index("ix_plans_employee", "employee_id", "status"))
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_code: Mapped[str] = mapped_column(String(30))
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    job_role_id: Mapped[int] = mapped_column(ForeignKey("job_roles.id"))
    matrix_version_id: Mapped[int | None] = mapped_column(ForeignKey("matrix_versions.id"))
    status: Mapped[str] = mapped_column(String(30), default="generating")
    score_coverage: Mapped[float | None] = mapped_column()
    score_traceability: Mapped[float | None] = mapped_column()
    score_traceability_mandatory: Mapped[float | None] = mapped_column()
    score_requirement_consistency: Mapped[float | None] = mapped_column()
    score_generation_consistency: Mapped[float | None] = mapped_column()
    count_missing: Mapped[int] = mapped_column(Integer, default=0)
    count_unsupported: Mapped[int] = mapped_column(Integer, default=0)
    count_contradictions: Mapped[int] = mapped_column(Integer, default=0)
    count_duplicates: Mapped[int] = mapped_column(Integer, default=0)
    outline: Mapped[dict] = mapped_column(JSONType, default=dict)
    timeline: Mapped[list] = mapped_column(JSONType, default=list)
    consistency: Mapped[dict | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    approved_by: Mapped[str | None] = mapped_column(String(254))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)

    employee: Mapped[Employee] = relationship()
    job_role: Mapped[JobRole] = relationship()
    matrix_version: Mapped["MatrixVersion | None"] = relationship()
    modules: Mapped[list["PlanModule"]] = relationship(back_populates="plan", cascade="all, delete-orphan",
                                                       order_by="PlanModule.position")


class GenerationRun(db.Model):
    """One Gemini call: the prompt, the raw response and every attempt (SRS Step 41, GenAI evidence)."""
    __tablename__ = "generation_runs"
    __table_args__ = (Index("ix_generation_runs_plan", "plan_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    phase: Mapped[str] = mapped_column(String(20))          # outline | module | consistency | regeneration
    module_key: Mapped[str | None] = mapped_column(String(10))
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(60))
    params: Mapped[dict] = mapped_column(JSONType, default=dict)
    prompt_template: Mapped[str] = mapped_column(String(60))
    prompt_version: Mapped[str] = mapped_column(String(20))
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    system_prompt: Mapped[str] = mapped_column(Text)
    user_prompt: Mapped[str] = mapped_column(Text)
    source_versions: Mapped[list] = mapped_column(JSONType, default=list)
    raw_response: Mapped[str] = mapped_column(Text, default="")
    parsed_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    schema_errors: Mapped[list] = mapped_column(JSONType, default=list)
    attempts: Mapped[list] = mapped_column(JSONType, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PlanModule(db.Model):
    __tablename__ = "plan_modules"
    __table_args__ = (UniqueConstraint("plan_id", "module_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    module_key: Mapped[str] = mapped_column(String(10))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(60))
    stage: Mapped[str] = mapped_column(String(10))
    purpose: Mapped[str] = mapped_column(Text, default="")
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=0)
    key_concepts: Mapped[list] = mapped_column(JSONType, default=list)
    required_sources: Mapped[list] = mapped_column(JSONType, default=list)
    activities: Mapped[list] = mapped_column(JSONType, default=list)
    assessment_topics: Mapped[list] = mapped_column(JSONType, default=list)
    completion_criteria: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[int | None] = mapped_column(ForeignKey("generation_runs.id"))
    content_ok: Mapped[bool] = mapped_column(Boolean, default=False)

    plan: Mapped[Plan] = relationship(back_populates="modules")
    items: Mapped[list["PlanItem"]] = relationship(back_populates="module", cascade="all, delete-orphan",
                                                   order_by="PlanItem.position")


ITEM_TYPES = ("objective", "checklist", "task", "scenario", "quiz_question", "assessment")


class PlanItem(db.Model):
    __tablename__ = "plan_items"
    __table_args__ = (CheckConstraint(_in("item_type", ITEM_TYPES), name="ck_plan_items_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("plan_modules.id", ondelete="CASCADE"))
    item_key: Mapped[str] = mapped_column(String(40), unique=True)
    item_type: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str | None] = mapped_column(String(10))
    difficulty: Mapped[str | None] = mapped_column(String(20))
    source_doc_id: Mapped[str | None] = mapped_column(String(30))
    source_section_id: Mapped[str | None] = mapped_column(String(60))
    content: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="Verified")

    module: Mapped[PlanModule] = relationship(back_populates="items")
    requirement_links: Mapped[list["PlanItemRequirement"]] = relationship(cascade="all, delete-orphan")


class PlanItemRequirement(db.Model):
    """Which requirements an item is based on: this table makes impact analysis a query."""
    __tablename__ = "plan_item_requirements"
    plan_item_id: Mapped[int] = mapped_column(ForeignKey("plan_items.id", ondelete="CASCADE"), primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), primary_key=True)


# --------------------------------------------------------------------------- verification

class ValidationRun(db.Model):
    __tablename__ = "validation_runs"
    __table_args__ = (Index("ix_validation_runs_plan", "plan_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    matrix_version_id: Mapped[int | None] = mapped_column(ForeignKey("matrix_versions.id"))
    matrix_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    ruleset_hash: Mapped[str] = mapped_column(String(64))
    plan_status: Mapped[str] = mapped_column(String(30))
    scores: Mapped[dict] = mapped_column(JSONType, default=dict)
    requirement_statuses: Mapped[dict] = mapped_column(JSONType, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    findings: Mapped[list["Finding"]] = relationship(cascade="all, delete-orphan")
    comparison_rows: Mapped[list["ComparisonRow"]] = relationship(cascade="all, delete-orphan")


class Finding(db.Model):
    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_run_rule", "validation_run_id", "rule_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    validation_run_id: Mapped[int] = mapped_column(ForeignKey("validation_runs.id", ondelete="CASCADE"))
    rule_id: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))            # error | warning | info
    status: Mapped[str] = mapped_column(String(40))              # item-level status it implies
    item_key: Mapped[str | None] = mapped_column(String(40))
    req_id: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONType, default=dict)


class ComparisonRow(db.Model):
    """GenAI result vs Python expectation for one requirement (SRS Step 46, report deliverable 6)."""
    __tablename__ = "comparison_rows"
    __table_args__ = (Index("ix_comparison_run", "validation_run_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    validation_run_id: Mapped[int] = mapped_column(ForeignKey("validation_runs.id", ondelete="CASCADE"))
    req_id: Mapped[str] = mapped_column(String(40))
    role_code: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(80))
    fields: Mapped[dict] = mapped_column(JSONType, default=dict)   # {field: {python, genai, match}}
    overall_match: Mapped[bool] = mapped_column(Boolean)
    coverage_status: Mapped[str] = mapped_column(String(30))
    traceability_status: Mapped[str] = mapped_column(String(30))
    validation_status: Mapped[str] = mapped_column(String(40))
    explanation: Mapped[str] = mapped_column(Text)


REVIEW_STATUSES_ITEM = ("open", "approved", "rejected", "edited", "regenerated", "overridden")


class ReviewItem(db.Model):
    """Something a person must decide before the plan reaches an employee (SRS Steps 48-49).

    target_type 'plan_item' points at a generated item (target_key = item_key); 'requirement' is a
    mandatory requirement the plan does not cover (target_key = req_id). The computed status is never
    changed: the reviewer's decision is recorded next to it, with the reason.
    """
    __tablename__ = "review_items"
    __table_args__ = (UniqueConstraint("plan_id", "target_type", "target_key"),
                      CheckConstraint(_in("status", REVIEW_STATUSES_ITEM), name="ck_review_items_status"),
                      Index("ix_review_items_status", "status", "created_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    target_type: Mapped[str] = mapped_column(String(20))
    target_key: Mapped[str] = mapped_column(String(60))
    plan_item_id: Mapped[int | None] = mapped_column(ForeignKey("plan_items.id", ondelete="CASCADE"))
    module_key: Mapped[str | None] = mapped_column(String(10))
    reasons: Mapped[list] = mapped_column(JSONType, default=list)     # [{rule_id, severity, status, message}]
    original_status: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="open")
    new_status: Mapped[str | None] = mapped_column(String(40))
    decision_by: Mapped[str | None] = mapped_column(String(254))
    decision_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    edit_diff: Mapped[dict | None] = mapped_column(JSONType)
    comments: Mapped[list] = mapped_column(JSONType, default=list)    # [{by, at, text}]
    carried_from_id: Mapped[int | None] = mapped_column(ForeignKey("review_items.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    plan: Mapped[Plan] = relationship()
    plan_item: Mapped["PlanItem | None"] = relationship()


CHANGE_STATUSES = ("open", "regenerated", "no_impact", "upcoming")


class ChangeImpact(db.Model):
    """A new document version compared with the version it replaces (SRS Steps 57-59).

    Only what changed is stored. Which plan items, plans and employees are affected is computed from
    plan_item_requirements when the page loads, so it is always current.
    """
    __tablename__ = "change_impacts"
    __table_args__ = (UniqueConstraint("from_document_id", "to_document_id"),
                      CheckConstraint(_in("status", CHANGE_STATUSES), name="ck_change_impacts_status"))
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(30), index=True)
    from_document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    to_document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    from_version: Mapped[str] = mapped_column(String(20))
    to_version: Mapped[str] = mapped_column(String(20))
    changes: Mapped[list] = mapped_column(JSONType, default=list)     # [{req_id, change, old_text, new_text, ...}]
    counts: Mapped[dict] = mapped_column(JSONType, default=dict)      # {changed, added, removed, unchanged}
    status: Mapped[str] = mapped_column(String(20), default="open")
    regenerated: Mapped[list] = mapped_column(JSONType, default=list) # [{plan_code, from_version, to_version, status}]
    created_by: Mapped[str] = mapped_column(String(254), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    from_document: Mapped[Document] = relationship(foreign_keys=[from_document_id])
    to_document: Mapped[Document] = relationship(foreign_keys=[to_document_id])


PROGRESS_STATUSES = ("not_started", "in_progress", "submitted", "completed", "failed", "waived")


class Progress(db.Model):
    """One employee's state on one plan item (SRS Step 53)."""
    __tablename__ = "progress"
    __table_args__ = (UniqueConstraint("employee_id", "plan_item_id"),
                      CheckConstraint(_in("status", PROGRESS_STATUSES), name="ck_progress_status"),
                      Index("ix_progress_plan", "plan_id", "employee_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    plan_item_id: Mapped[int] = mapped_column(ForeignKey("plan_items.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="not_started")
    score: Mapped[float | None] = mapped_column()
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    due_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    content_updated: Mapped[bool] = mapped_column(Boolean, default=False)   # reset by a policy update
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_by: Mapped[str | None] = mapped_column(String(254))

    plan_item: Mapped["PlanItem"] = relationship()


class QuizAttempt(db.Model):
    """One attempt at a module quiz, scored by Python against the generated answer key."""
    __tablename__ = "quiz_attempts"
    __table_args__ = (UniqueConstraint("employee_id", "plan_id", "module_key", "attempt_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    module_key: Mapped[str] = mapped_column(String(10))
    attempt_no: Mapped[int] = mapped_column(Integer)
    answers: Mapped[list] = mapped_column(JSONType, default=list)   # [{item_key, selected, correct, requirement_id}]
    score: Mapped[float] = mapped_column()
    passed: Mapped[bool] = mapped_column(Boolean)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


RECOMMENDATION_TYPES = ("revision_module", "additional_quiz", "additional_task", "advanced_module", "manager_review")


class Recommendation(db.Model):
    """A rule-based suggestion from measured progress signals (SRS Steps 55-56). A person decides."""
    __tablename__ = "recommendations"
    __table_args__ = (UniqueConstraint("employee_id", "plan_id", "rule_id", "module_key"),
                      CheckConstraint(_in("type", RECOMMENDATION_TYPES), name="ck_recommendations_type"),
                      CheckConstraint(_in("status", ("open", "accepted", "dismissed", "done")), name="ck_recommendations_status"))
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    rule_id: Mapped[str] = mapped_column(String(30))
    type: Mapped[str] = mapped_column(String(20))
    module_key: Mapped[str] = mapped_column(String(10), default="")
    text: Mapped[str] = mapped_column(Text)
    signals: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="open")
    decided_by: Mapped[str | None] = mapped_column(String(254))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Certificate(db.Model):
    """Proof of completed onboarding, issued only when every tracked item of the assigned plan is done.
    Anyone can check it at /verify/<code>."""
    __tablename__ = "certificates"
    __table_args__ = (UniqueConstraint("employee_id", "plan_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    details: Mapped[dict] = mapped_column(JSONType, default=dict)   # modules, items, quiz average at issue time

    employee: Mapped[Employee] = relationship()
    plan: Mapped[Plan] = relationship()


# --------------------------------------------------------------------------- audit trail

class AuditLog(db.Model):
    """Append-only. The ORM refuses updates and deletes; on PostgreSQL the app role also lacks the privilege
    (database/postgres_hardening.sql)."""
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id", "ts"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[dict] = mapped_column(JSONType, default=dict)
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(120))
    entity_version: Mapped[str | None] = mapped_column(String(20))
    before: Mapped[dict | None] = mapped_column(JSONType)
    after: Mapped[dict | None] = mapped_column(JSONType)
    reason: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSONType)


@event.listens_for(AuditLog, "before_update")
@event.listens_for(AuditLog, "before_delete")
def _audit_is_append_only(mapper, connection, target):
    raise PermissionError("audit_log is append-only")


# ---------------------------------------------------------------------------- SkillSprint (the product company)
# These tables belong to SkillSprint itself, not to a client workspace: its own staff, demo requests from the
# public site, and the temporary read-only accounts given to approved requests.

class PlatformStaff(db.Model):
    """SkillSprint staff who use the console. They cannot open a client workspace."""
    __tablename__ = "platform_staff"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DemoRequest(db.Model):
    """A 'Request a demo' form from the public site, followed up in the console."""
    __tablename__ = "demo_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254), index=True)
    company: Mapped[str] = mapped_column(String(200))
    job_title: Mapped[str] = mapped_column(String(120), default="")
    company_size: Mapped[str] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(80), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    consent: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="new")       # new | contacted | booked | approved | won | lost
    note: Mapped[str] = mapped_column(Text, default="")
    ip_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    handled_by: Mapped[str | None] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DemoAccount(db.Model):
    """A temporary, read-only sign-in for an approved demo request. It stops working at expires_at."""
    __tablename__ = "demo_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("demo_requests.id", ondelete="SET NULL"))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    login_count: Mapped[int] = mapped_column(Integer, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str] = mapped_column(String(254), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    request: Mapped["DemoRequest | None"] = relationship()


class DemoVisit(db.Model):
    """A page a demo account opened. Recorded only for demo accounts, which are told about it on the form."""
    __tablename__ = "demo_visits"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("demo_accounts.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    endpoint: Mapped[str] = mapped_column(String(80))
    path: Mapped[str] = mapped_column(String(300))


# --------------------------------------------------------------------------- Ask the bot

BOT_STATUSES = ("answered", "no_source", "blocked", "escalated", "manager_answered")


class BotQuestion(db.Model):
    """A question an employee asked the bot, what the sources and the checks decided, and any manager reply.

    answered          the bot answered from approved passages and Python accepted the answer
    no_source         no approved passage covers the question; Gemini was not asked (or said it cannot answer)
    blocked           Gemini answered but Python rejected it (unknown citation or a fact not in the sources)
    escalated         the employee sent it to their line manager
    manager_answered  the line manager replied
    """
    __tablename__ = "bot_questions"
    __table_args__ = (CheckConstraint(_in("status", BOT_STATUSES), name="ck_bot_questions_status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    module_key: Mapped[str | None] = mapped_column(String(10))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    score: Mapped[float] = mapped_column(default=0.0)                 # best passage's share of the question's key words
    answer: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list] = mapped_column(JSONType, default=list)     # [{ref, doc_id, section_id, text, cited}]
    check: Mapped[dict] = mapped_column(JSONType, default=dict)       # what Python checked and why it decided
    run_id: Mapped[int | None] = mapped_column(ForeignKey("generation_runs.id", ondelete="SET NULL"))
    helpful: Mapped[bool | None] = mapped_column(Boolean)
    manager_code: Mapped[str | None] = mapped_column(String(20), index=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime)
    manager_answer: Mapped[str] = mapped_column(Text, default="")
    answered_by: Mapped[str | None] = mapped_column(String(254))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    employee: Mapped["Employee"] = relationship()
