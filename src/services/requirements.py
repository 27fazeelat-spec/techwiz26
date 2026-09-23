"""Persist extracted requirements, keep their lineage across versions, and link them together."""
import re

from sqlalchemy import select

from config.loader import load_config
from database import db
from database.models import Chunk, Document, JobRole, Requirement, RequirementPrerequisite
from document_processing.metadata import version_key
from role_matrix import lineage
from role_matrix.applicability import resolve_roles
from role_matrix.extractor import Rules, detect_condition, extract_from_chunk

TRAINING_DEF = re.compile(
    r"\bcomplete\s+(?:the\s+)?([A-Z][\w&/ -]*?)\s+(?:training|module|e-learning module|certification|course|orientation)\b")


def _source_lines(chunk):
    """Chunk text for extraction: one line per block, hidden text removed."""
    text = chunk.text
    if chunk.hidden_text:
        hidden = " ".join(chunk.hidden_text.replace("​", "").split())
        text = "\n".join(line for line in text.split("\n") if " ".join(line.split()) != hidden)
        text = text.replace(hidden, " ")
    return text


def _previous_version(doc):
    versions = db.session.scalars(select(Document).where(Document.doc_id == doc.doc_id, Document.id != doc.id)).all()
    older = [v for v in versions if version_key(v.version) < version_key(doc.version)]
    return max(older, key=lambda v: version_key(v.version)) if older else None


def extract_document_requirements(doc, roles=None, rules=None):
    """Extract, number and store requirements for one document version. Returns the new rows."""
    if doc.tier == 0:
        return []
    rules = rules or Rules()
    roles = roles if roles is not None else db.session.scalars(select(JobRole)).all()
    actors = load_config("extraction").get("actors", []) + [r.name for r in roles]
    audience_condition = detect_condition(doc.applies_to_text or "", rules)

    found = []
    for chunk in doc.chunks:
        if chunk.quarantined or chunk.section_id == "footer":
            continue
        for item in extract_from_chunk(_source_lines(chunk), doc.doc_id, doc.title, chunk.heading_path, actors, rules):
            found.append((chunk, item))

    prev_doc = _previous_version(doc)
    prev_rows = db.session.scalars(select(Requirement).where(Requirement.document_id == prev_doc.id)
                                   .order_by(Requirement.position)).all() if prev_doc else []
    cfg = load_config("extraction")["lineage"]
    matches = lineage.match([{"section_id": c.section_id, "text": e.text} for c, e in found],
                            [{"section_id": r.section_id, "text": r.text, "row": r} for r in prev_rows],
                            cfg["same_section_min_ratio"], cfg["any_section_min_ratio"])

    existing_numbers = [int(n) for n in db.session.scalars(
        select(Requirement.req_id).where(Requirement.doc_id == doc.doc_id)).all()
        for n in re.findall(r"-(\d{3})$", n)]
    next_number = max(existing_numbers, default=0) + 1

    rows = []
    for position, ((chunk, item), (prev, change)) in enumerate(zip(found, matches), start=1):
        if prev is not None:
            req_id, previous = prev["row"].req_id, prev["row"]
        else:
            req_id, previous = f"R-{doc.doc_id}-{next_number:03d}", None
            next_number += 1
        rows.append(Requirement(
            req_id=req_id, document=doc, chunk=chunk, doc_id=doc.doc_id, version=doc.version,
            section_id=chunk.section_id, position=position, text=item.text, req_type=item.req_type,
            mandatory=item.mandatory, modality=item.modality,
            roles=resolve_roles(item.subject, chunk.heading_path, doc.applies_to_text, roles),
            subject=item.subject, condition=item.condition or audience_condition, due_stage=item.due_stage,
            stage_source=item.stage_source, priority=item.priority, competency=item.competency,
            assessment_type=item.assessment_type, facts=item.facts, cross_refs=item.cross_refs,
            lineage_change=change, previous=previous))
    db.session.add_all(rows)
    return rows


def link_requirements():
    """Resolve cross-references and training prerequisites across all current requirements.

    Run after a batch of documents is ingested (and before building the matrix), because links
    can point to documents ingested later in the batch.
    """
    current = db.session.execute(
        select(Requirement, Document).join(Document, Requirement.document_id == Document.id)
        .where(Document.status.in_(["active", "expired"]))).all()
    documents = db.session.scalars(select(Document)).all()
    doc_ids = {d.doc_id for d in documents}
    annexes = {(c.doc_id, c.section_id) for c in db.session.scalars(
        select(Chunk).where(Chunk.section_id.like("Annex %")))}

    trainings = {}
    for req, _ in current:
        m = TRAINING_DEF.search(req.text)
        if m and req.req_type == "Must Complete":
            trainings.setdefault(m.group(1).lower(), req)

    links = set()
    for req, doc in current:
        refs = []
        for ref in req.cross_refs or []:
            ref = dict(ref)
            if ref["type"] == "document":
                ref["resolved"] = ref["doc_id"] in doc_ids
                target = next((r for r, d in current if d.doc_id == ref["doc_id"] and r.section_id == ref.get("section_id")), None)
                if target is not None and target.id != req.id:
                    links.add((req.id, target.id, "cross_reference"))
            elif ref["type"] == "annex":
                ref["resolved"] = (doc.doc_id, ref["section_id"]) in annexes
            else:
                words = ref["name"].rsplit(" ", 1)[0].lower()
                kind = ref["name"].rsplit(" ", 1)[-1]
                ref["resolved"] = any(words in (d.title or "").lower() and
                                      (kind != "SOP" or d.category == "SOP") for d in documents)
            refs.append(ref)
        req.cross_refs = refs
        lowered = req.text.lower()
        for name, defining in trainings.items():
            if defining.id != req.id and name in lowered and re.search(r"\b(before|after|until)\b", lowered):
                links.add((req.id, defining.id, "training_reference"))

    db.session.query(RequirementPrerequisite).delete()
    db.session.add_all(RequirementPrerequisite(requirement_id=a, prerequisite_id=b, source=s) for a, b, s in links)
    return len(links)
