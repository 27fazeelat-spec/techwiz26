"""Source bundle for one employee: the document text Gemini is allowed to see.

  - active (or expired, marked as such) documents with a precedence tier > 0
  - documents whose audience includes the employee's role or everyone
  - role-description documents: only the sections about this role
  - never quarantined chunks, never hidden text
Each requirement clause is prefixed with its ID, but none of the matrix attributes (mandatory flag,
roles, stage, priority) are included: Gemini must infer them, and Python checks them independently.
"""
import re
from dataclasses import dataclass, field

from sqlalchemy import select

from database import db
from database.models import Document, JobRole, Requirement
from role_matrix.applicability import _mentions, audience


@dataclass
class SourceBundle:
    text: str
    chunks: list = field(default_factory=list)          # Chunk rows included
    requirement_ids: set = field(default_factory=set)
    documents: list = field(default_factory=list)       # (doc_id, version)
    sections: list = field(default_factory=list)        # [{header, text, req_ids}] for per-module subsets

    def subset(self, req_ids):
        """Source text limited to the sections that contain the given requirements (Phase 2 prompts)."""
        wanted = set(req_ids)
        by_header = {}
        for s in self.sections:
            if s["req_ids"] & wanted:
                by_header.setdefault(s["header"], []).append(s["text"])
        return "\n\n".join(header + "\n" + "\n\n".join(texts) for header, texts in by_header.items())


def _annotate(chunk, reqs, overridden=frozenset()):
    """Prefix each clause with its ID; drop clauses overridden by a higher-precedence rule."""
    text = chunk.source_text
    for r in sorted(reqs, key=lambda r: -len(r.text)):
        text = text.replace(r.text, "" if r.id in overridden else f"[{r.req_id}] {r.text}", 1)
    return text


def build_bundle(role):
    roles = db.session.scalars(select(JobRole)).all()
    docs = db.session.scalars(select(Document).where(Document.status.in_(["active", "expired"]), Document.tier > 0)
                              .order_by(Document.tier, Document.doc_id)).all()
    doc_ids = [d.id for d in docs]
    reqs_by_chunk = {}
    for r in db.session.scalars(select(Requirement).where(Requirement.document_id.in_(doc_ids),
                                                          Requirement.review_status != "rejected")):
        reqs_by_chunk.setdefault(r.chunk_id, []).append(r)

    from src.services.conflicts import losing_requirement_ids
    overridden = losing_requirement_ids()
    bundle = SourceBundle(text="")
    parts = []
    for doc in docs:
        who = audience(doc.applies_to_text, roles)
        if who != ["ALL"] and role.code not in who and doc.category != "Role Description":
            continue
        status = " (EXPIRED - no current replacement)" if doc.status == "expired" else ""
        header = f"=== {doc.doc_id} v{doc.version} · {doc.title} · {doc.category}{status} ==="
        texts = []
        for chunk in doc.chunks:
            if chunk.quarantined or chunk.section_id in ("footer", "revision-history"):
                continue
            if doc.category == "Role Description" and role.code not in _mentions(" ".join(chunk.heading_path), roles):
                continue
            reqs = reqs_by_chunk.get(chunk.id, [])
            text = f"[§{chunk.section_id}] {chunk.heading or chunk.section_id}\n{_annotate(chunk, reqs, overridden)}"
            reqs = [r for r in reqs if r.id not in overridden]
            texts.append(text)
            bundle.chunks.append(chunk)
            bundle.requirement_ids.update(r.req_id for r in reqs)
            bundle.sections.append({"header": header, "text": text, "req_ids": {r.req_id for r in reqs}})
        if texts:
            parts.append(header + "\n" + "\n\n".join(texts))
            bundle.documents.append((doc.doc_id, doc.version))
    bundle.text = "\n\n".join(parts)
    return bundle


def employee_brief(employee):
    prop = employee.property
    return {
        "employee_id": employee.employee_code, "role": employee.job_role.name, "role_code": employee.job_role.code,
        "department": employee.department,
        "property": {"code": prop.code, "name": prop.name, "country": prop.country, "type": prop.type,
                     "services": prop.services},
        "experience_level": employee.experience_level, "experience_years": employee.experience_years,
        "previous_experience": employee.previous_experience, "joining_date": employee.joining_date.isoformat(),
        "shift_pattern": employee.shift_pattern, "certifications": employee.certifications,
        "assignments": employee.assignments,
    }


def token_estimate(text):
    return len(re.findall(r"\S+", text)) * 4 // 3
