"""Policy updates: what changed, what it affects, and selective regeneration (SRS Steps 57-59).

1. Detection: a new document version is compared clause by clause with the version it replaces,
   using the requirement lineage (a changed clause keeps its requirement ID).
2. Impact: plan items are linked to the requirement rows they were generated from
   (plan_item_requirements), so "which items, plans and employees" is a query, not a guess.
3. Regeneration: only the affected modules are regenerated; every other module is copied, and the
   whole new plan version is re-validated. It needs a matrix approved after the change.
"""
import re
from collections import Counter
from difflib import SequenceMatcher

from sqlalchemy import select

from database import audit, db
from database.models import (ChangeImpact, Document, MatrixRow, MatrixVersion, Plan, PlanItem, PlanItemRequirement,
                             PlanModule, Requirement)
from document_processing.metadata import version_key

NUMBER = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|°c|days?|hours?|minutes?|months?|years?|weeks?|usd|aed|omr|myr)?", re.I)


class ChangeError(ValueError):
    pass


def word_diff(old, new):
    """[(op, text)] with op in equal / delete / insert, word by word, for display."""
    a, b = (old or "").split(), (new or "").split()
    out = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(("equal", " ".join(a[i1:i2])))
        else:
            if i2 > i1:
                out.append(("delete", " ".join(a[i1:i2])))
            if j2 > j1:
                out.append(("insert", " ".join(b[j1:j2])))
    return out


def _facts(text):
    return sorted({m.group(0).strip().lower() for m in NUMBER.finditer(text or "")})


# --------------------------------------------------------------------------- detection

def compare_versions(old_doc, new_doc):
    old = {r.req_id: r for r in db.session.scalars(select(Requirement).where(Requirement.document_id == old_doc.id))}
    new = {r.req_id: r for r in db.session.scalars(select(Requirement).where(Requirement.document_id == new_doc.id))}
    changes, counts = [], Counter()
    for req_id in sorted(set(old) | set(new)):
        o, n = old.get(req_id), new.get(req_id)
        if o and n and o.text == n.text and o.mandatory == n.mandatory:
            counts["unchanged"] += 1
            continue
        kind = "changed" if o and n else ("removed" if o else "added")
        counts[kind] += 1
        entry = {"req_id": req_id, "change": kind, "section_id": (n or o).section_id,
                 "old_text": o.text if o else None, "new_text": n.text if n else None,
                 "old_mandatory": o.mandatory if o else None, "new_mandatory": n.mandatory if n else None}
        if kind == "changed":
            old_f, new_f = _facts(o.text), _facts(n.text)
            entry["facts"] = {"removed": [f for f in old_f if f not in new_f], "added": [f for f in new_f if f not in old_f]}
        changes.append(entry)
    return changes, dict(counts)


def detect_changes(doc_id=None, actor=None):
    """Record a ChangeImpact for every (previous version -> newer active or scheduled version) pair
    that has not been recorded yet. Idempotent. Returns the new rows."""
    query = select(Document).where(Document.tier > 0)
    if doc_id:
        query = query.where(Document.doc_id == doc_id)
    by_lineage = {}
    for d in db.session.scalars(query):
        by_lineage.setdefault(d.doc_id, []).append(d)
    known = {(c.from_document_id, c.to_document_id) for c in db.session.scalars(select(ChangeImpact))}
    created = []
    for versions in by_lineage.values():
        versions.sort(key=lambda d: version_key(d.version))
        usable = [d for d in versions if d.status in ("active", "superseded", "scheduled", "expired")]
        for old, new in zip(usable, usable[1:]):
            if (old.id, new.id) in known or new.status not in ("active", "scheduled", "expired"):
                continue
            changes, counts = compare_versions(old, new)
            row = ChangeImpact(doc_id=new.doc_id, from_document_id=old.id, to_document_id=new.id,
                               from_version=old.version, to_version=new.version, changes=changes, counts=counts,
                               status="upcoming" if new.status == "scheduled" else "open",
                               created_by=(actor or {}).get("email", "system"))
            db.session.add(row)
            created.append(row)
            audit.record("policy.change_detected", "document", new.doc_id, actor=actor, version=new.version,
                         after={"from": old.version, **counts}, commit=False)
    db.session.flush()
    for row in created:
        if not impact(row)["plans"] and row.status == "open":
            row.status = "no_impact"
    return created


def refresh_status(change):
    """Scheduled versions become active on their effective date; the change then becomes actionable."""
    if change.status == "upcoming" and change.to_document.status == "active":
        change.status = "open" if impact(change)["plans"] else "no_impact"


# --------------------------------------------------------------------------- impact

def impact(change):
    """Affected items, modules, plans and employees, computed live from plan_item_requirements."""
    touched = {c["req_id"] for c in change.changes if c["change"] in ("changed", "removed")}
    old_rows = {r.id: r.req_id for r in db.session.scalars(
        select(Requirement).where(Requirement.document_id == change.from_document_id, Requirement.req_id.in_(touched)))} if touched else {}
    rows = db.session.execute(
        select(PlanItem, PlanModule, Plan, PlanItemRequirement.requirement_id)
        .join(PlanItemRequirement, PlanItemRequirement.plan_item_id == PlanItem.id)
        .join(PlanModule, PlanItem.module_id == PlanModule.id).join(Plan, PlanModule.plan_id == Plan.id)
        .where(PlanItemRequirement.requirement_id.in_(list(old_rows)), Plan.status != "superseded")).all() if old_rows else []
    plans = {}
    for item, module, plan, req_row in rows:
        p = plans.setdefault(plan.id, {"plan": plan, "modules": {}, "items": set(), "by_type": Counter()})
        m = p["modules"].setdefault(module.module_key, {"title": module.title, "requirements": set(), "items": Counter()})
        m["requirements"].add(old_rows[req_row])
        if item.id not in p["items"]:
            p["items"].add(item.id)
            p["by_type"][item.item_type] += 1
            m["items"][item.item_type] += 1
    added = [c["req_id"] for c in change.changes if c["change"] == "added"]
    by_type = Counter()
    for p in plans.values():
        by_type.update(p["by_type"])
    ordered = sorted(plans.values(), key=lambda p: (p["plan"].employee.name, p["plan"].version))
    return {"plans": ordered, "employees": len({p["plan"].employee_id for p in ordered}),
            "items": sum(len(p["items"]) for p in ordered), "by_type": dict(by_type),
            "assigned": sum(1 for p in ordered if p["plan"].approved_at), "added": added}


# --------------------------------------------------------------------------- regeneration

def regeneration_blockers(change):
    blockers = []
    if change.to_document.status != "active":
        blockers.append(f"{change.doc_id} v{change.to_version} is not in force yet ({change.to_document.status}).")
    approved = db.session.scalar(select(MatrixVersion).where(MatrixVersion.status == "approved")
                                 .order_by(MatrixVersion.version_no.desc()))
    if approved is None or approved.approved_at is None or approved.approved_at < change.created_at:
        blockers.append("Build and approve a new Role Requirement Matrix first, so plans are checked against the updated policy.")
    return blockers


def regenerate_for_change(change, actor, app_config, plan_ids=None, provider=None):
    """Regenerate only the affected modules of each affected plan. Returns [(old plan, new plan)]."""
    from src.services.planning import current_matrix, regenerate_modules
    blockers = regeneration_blockers(change)
    if blockers:
        raise ChangeError(" ".join(blockers))
    info = impact(change)
    targets = [p for p in info["plans"] if plan_ids is None or p["plan"].id in plan_ids]
    if not targets:
        raise ChangeError("No current plan is affected by this change.")
    removed = [c["req_id"] for c in change.changes if c["change"] == "removed"]
    matrix = current_matrix()
    results = []
    for p in targets:
        plan = p["plan"]
        in_matrix = set(db.session.scalars(
            select(Requirement.req_id).join(MatrixRow, MatrixRow.requirement_id == Requirement.id)
            .where(MatrixRow.matrix_version_id == matrix.id, MatrixRow.job_role_id == plan.job_role_id,
                   Requirement.req_id.in_(info["added"])))) if info["added"] else set()
        new_plan = regenerate_modules(
            plan, sorted(p["modules"]), actor, app_config, provider=provider,
            reason=f"Policy update {change.doc_id} v{change.from_version} -> v{change.to_version}",
            add_requirements=sorted(in_matrix), drop_requirements=removed)
        results.append((plan, new_plan))
        change.regenerated = change.regenerated + [{"plan_code": plan.plan_code, "from_version": plan.version,
                                                    "to_version": new_plan.version, "status": new_plan.status,
                                                    "modules": sorted(p["modules"])}]
    if not impact(change)["plans"]:
        change.status = "regenerated"
    audit.record("policy.regenerated", "document", change.doc_id, actor=actor, version=change.to_version,
                 after={"plans": [f"{a.plan_code} v{a.version} -> v{b.version}" for a, b in results]}, commit=False)
    db.session.commit()
    return results
