"""Tidy a stored plan's items with Python rules, after Gemini has written them.

  1. Stage from the approved matrix. Every item is due at the stage of the requirement it teaches, not at the
     module's earliest stage and not at the stage Gemini typed. The module assessment comes last: the latest stage
     among the module's requirements.
  2. Checklists are for actions. A checklist item stays when it is something to do once (it starts with an action
     verb, or its requirement must be completed, signed, acknowledged ...: config/genai.yaml plan.checklist_*), or
     when nothing else in the plan teaches that requirement. Working rules ("verify the guest's ID", "apply the check-out fee") are taught by the tasks,
     scenarios and quizzes that cover them.
  3. One item per action. Checklist items that describe the same action at the same stage (for example the same
     orientation named in two documents) become one item that cites both requirements.

Used when a plan is stored (new or regenerated) and, once, for plans stored before these rules (restage command).
Items the employee has already worked on are never removed or merged.
"""
import re
from datetime import timedelta

from sqlalchemy import select

from config.loader import load_config
from database import db
from database.models import MatrixRow, PlanItemRequirement, Progress, Requirement

WORD = re.compile(r"[a-z]+")
PASSIVE_ACTION = re.compile(r"must be (completed|signed|attended|acknowledged|submitted|collected|declared)", re.I)
FILLER = {"the", "and", "a", "an", "of", "to", "on", "in", "at", "for", "your", "you", "all", "any", "with", "by",
          "complete", "attend", "first", "day", "working", "before", "after", "must", "be", "is", "are", "their"}


def _words(text):
    return {w for w in WORD.findall((text or "").lower()) if w not in FILLER and len(w) > 2}


def _text(item):
    c = item.content or {}
    return c.get("activity") or c.get("description") or c.get("text") or ""


def tidy(plan, dry_run=False):
    """Apply the three rules to plan's items. Returns a summary; changes nothing when dry_run is True."""
    cfg = load_config("genai")["plan"]
    keep_types = set(cfg.get("checklist_types", ["Must Complete", "Must Acknowledge"]))
    overlap_at = cfg.get("checklist_merge_overlap", 0.8)
    order = {s["code"]: i for i, s in enumerate(load_config("stages")["stages"])}

    matrix_stage = dict(db.session.execute(
        select(Requirement.req_id, MatrixRow.due_stage).join(Requirement, MatrixRow.requirement_id == Requirement.id)
        .where(MatrixRow.matrix_version_id == plan.matrix_version_id, MatrixRow.job_role_id == plan.job_role_id)).all())
    outline = {r["requirement_id"]: r for r in (plan.outline or {}).get("requirements", [])}
    req_type, req_text = {}, {}
    for rid, rtype, text in db.session.execute(select(Requirement.req_id, Requirement.req_type, Requirement.text)
                                               .where(Requirement.req_id.in_(list(outline) or [""]))
                                               .order_by(Requirement.id)):
        req_type[rid], req_text[rid] = rtype, text                    # the newest version wins
    verbs = {v.lower() for v in cfg.get("checklist_action_verbs", [])}

    def is_action(item, ids):
        first = (WORD.findall(_text(item).lower()) or [""])[0]
        return (first in verbs or any(req_type.get(r) in keep_types for r in ids)
                or any(PASSIVE_ACTION.search(req_text.get(r) or "") for r in ids))
    started = set(db.session.scalars(select(Progress.plan_item_id).where(
        Progress.plan_id == plan.id, Progress.status.notin_(["not_started"]))))

    def stage_of(req_id):
        return matrix_stage.get(req_id) or (outline.get(req_id) or {}).get("due_stage")

    items = [i for m in plan.modules for i in m.items]
    summary = {"plan": f"{plan.plan_code} v{plan.version}", "restaged": 0, "dropped": [], "merged": [],
               "day1_before": sum(i.stage == "D1" and i.item_type != "objective" for i in items)}
    new_stage = {}
    for m in plan.modules:
        module_reqs = [r for r, o in outline.items() if o.get("module_key") == m.module_key]
        for i in m.items:
            ids = (i.content or {}).get("requirement_ids") or []
            if i.item_type == "assessment":
                stages = [stage_of(r) for r in module_reqs if stage_of(r)]
                stage = max(stages, key=lambda s: order.get(s, -1)) if stages else i.stage
            else:
                stages = [stage_of(r) for r in ids if stage_of(r)]
                stage = min(stages, key=lambda s: order.get(s, 99)) if stages else i.stage
            new_stage[i.id] = stage or i.stage or m.stage
    summary["restaged"] = sum(new_stage[i.id] != i.stage for i in items)

    taught = {}
    for i in items:
        if i.item_type not in ("objective", "checklist"):
            for r in (i.content or {}).get("requirement_ids") or []:
                taught[r] = taught.get(r, 0) + 1
    drop = set()
    for i in items:
        ids = (i.content or {}).get("requirement_ids") or []
        if i.item_type != "checklist" or i.id in started or not ids:
            continue
        if not is_action(i, ids) and all(taught.get(r) for r in ids):
            drop.add(i.id)
            summary["dropped"].append(f"{i.item_key}: {_text(i)[:70]}")

    merges = []                                           # (kept item, merged item)
    kept = []
    for i in items:
        if i.item_type != "checklist" or i.id in drop:
            continue
        words = _words(_text(i))
        twin = next((k for k, kw in kept if new_stage[k.id] == new_stage[i.id] and len(words) >= 3 and len(kw) >= 3
                     and len(words & kw) / min(len(words), len(kw)) >= overlap_at), None)
        if twin is not None and i.id not in started:
            merges.append((twin, i))
            summary["merged"].append(f"{i.item_key} into {twin.item_key}: {_text(i)[:60]}")
        else:
            kept.append((i, words))

    remaining = [i for i in items if i.id not in drop and i not in {b for _, b in merges}]
    day1 = [i for i in remaining if new_stage[i.id] == "D1" and i.item_type != "objective"]
    summary["day1_after"] = len(day1)
    summary["day1_items"] = [f"{i.item_type}: {_text(i)[:70] or (i.content or {}).get('question', '')[:70]}" for i in day1]
    if dry_run:
        return summary

    for i in items:
        i.stage = new_stage[i.id]
    rows = {r.req_id: r.id for r in db.session.scalars(select(Requirement).where(
        Requirement.req_id.in_([r for _, b in merges for r in (b.content or {}).get("requirement_ids", [])] or [""])))}
    for a, b in merges:
        ids = list(dict.fromkeys(((a.content or {}).get("requirement_ids") or []) + ((b.content or {}).get("requirement_ids") or [])))
        also = list((a.content or {}).get("also_cited", [])) + [{"source_document_id": b.source_doc_id,
                                                                  "source_section_id": b.source_section_id}]
        a.content = {**a.content, "requirement_ids": ids, "also_cited": also}
        linked = {l.requirement_id for l in a.requirement_links}
        for r in (b.content or {}).get("requirement_ids") or []:
            if rows.get(r) and rows[r] not in linked:
                a.requirement_links.append(PlanItemRequirement(requirement_id=rows[r]))
                linked.add(rows[r])
    for i in items:
        if i.id in drop or i in {b for _, b in merges}:
            db.session.delete(i)
    _redate(plan, new_stage)
    db.session.flush()
    for m in plan.modules:
        db.session.expire(m, ["items"])                   # removed items leave the module's list
    return summary


def _redate(plan, new_stage):
    """Assigned plans: due dates follow the new stages for items the employee has not started."""
    joining = plan.employee.joining_date
    if not joining:
        return
    offsets = {s["code"]: s["day_offset"] for s in load_config("stages")["stages"]}
    for row in db.session.scalars(select(Progress).where(Progress.plan_id == plan.id, Progress.status == "not_started")):
        stage = new_stage.get(row.plan_item_id)
        if stage in offsets:
            row.due_date = joining + timedelta(days=offsets[stage])
