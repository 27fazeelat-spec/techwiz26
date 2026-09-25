"""Review queue, reviewer decisions and the assignment gate (SRS Steps 48-49, NFR 4).

Python decides what needs a person (config: validation_rules.yaml > review). A person decides what
happens to it. The computed status is never overwritten: every decision is stored next to it, with
the reviewer, the time and a reason, and is written to the append-only audit trail.
"""
from pydantic import ValidationError
from sqlalchemy import func, select

from config.loader import load_config
from database import audit, db, utcnow
from database.models import Plan, PlanItem, PlanItemRequirement, Requirement, ReviewItem, ValidationRun
from python_validation.statuses import worst
from schemas.plan import Assessment, ChecklistItem, Objective, QuizQuestion, Scenario, Task

ITEM_SCHEMAS = {"objective": Objective, "checklist": ChecklistItem, "task": Task, "scenario": Scenario,
                "quiz_question": QuizQuestion, "assessment": Assessment}
DECISIONS = ("approve", "reject", "edit", "override", "regenerate", "comment")
RESOLVED = ("approved", "rejected", "edited", "regenerated", "overridden")
PAST = {"approve": "approved", "reject": "rejected", "edit": "edited", "override": "overridden",
        "regenerate": "regenerated"}


class ReviewError(ValueError):
    pass


def cfg():
    return load_config("validation_rules")["review"]


def code(item):
    return f"RV-{item.id:05d}"


def latest_run(plan):
    return db.session.scalar(select(ValidationRun).where(ValidationRun.plan_id == plan.id)
                             .order_by(ValidationRun.created_at.desc(), ValidationRun.id.desc()))


def _reasons(findings):
    return [{"rule_id": f.rule_id, "severity": f.severity, "status": f.status, "message": f.message}
            for f in findings if f.severity != "info"]


# --------------------------------------------------------------------------- routing

def route_for_review(plan, run, carry=None):
    """Create or refresh review items for a freshly validated plan.

    carry: {"plan": previous plan version, "keys": {old item_key: new item_key}} to bring forward the
    decisions made on items that were copied unchanged into this version.
    """
    c = cfg()
    by_item, by_req = {}, {}
    for f in run.findings:
        if f.severity == "info":
            continue
        if f.item_key:
            by_item.setdefault(f.item_key, []).append(f)
        elif f.req_id:                      # requirement-level: missing, or included when it should not be
            by_req.setdefault(f.req_id, []).append(f)

    wanted = {}
    for m in plan.modules:
        for item in m.items:
            if item.status in c["route_item_statuses"]:
                wanted[("plan_item", item.item_key)] = (item, m.module_key, item.status, _reasons(by_item.get(item.item_key, [])))
    requirement_statuses = set(c["route_item_statuses"])
    if c.get("route_missing_requirements", True):
        requirement_statuses.add("Requirement Missing")
    for req_id, fs in by_req.items():
        flagged = [f for f in fs if f.status in requirement_statuses]
        if flagged:
            wanted[("requirement", req_id)] = (None, None, worst([f.status for f in flagged]), _reasons(fs))

    existing = {(r.target_type, r.target_key): r for r in
                db.session.scalars(select(ReviewItem).where(ReviewItem.plan_id == plan.id))}
    for key, r in existing.items():
        if key in wanted:
            item, _, status, reasons = wanted[key]
            r.reasons, r.original_status = reasons, status
            if r.status == "edited":        # the edit did not fix it: back to the reviewer
                r.status = "open"
                r.comments = r.comments + [{"by": "system", "at": utcnow().isoformat(timespec="seconds"),
                                            "text": f"After the edit, Python still reports: {status}."}]
        elif r.status == "open":            # Python no longer reports a problem: nothing to decide
            db.session.delete(r)

    carried = _carried_decisions(carry)
    for key, (item, module_key, status, reasons) in wanted.items():
        if key in existing:
            continue
        r = ReviewItem(plan_id=plan.id, target_type=key[0], target_key=key[1], plan_item=item,
                       module_key=module_key, reasons=reasons, original_status=status, status="open", comments=[])
        prior = carried.get(key)
        if prior is not None:
            r.status, r.new_status, r.carried_from_id = prior.status, prior.new_status, prior.id
            r.decision_by, r.decision_at, r.decision_reason = prior.decision_by, prior.decision_at, prior.decision_reason
            r.comments = [{"by": "system", "at": utcnow().isoformat(timespec="seconds"),
                           "text": f"Decision carried over from {prior.plan.plan_code} v{prior.plan.version} "
                                   f"(the item was copied unchanged)."}]
        db.session.add(r)
    db.session.flush()


def _carried_decisions(carry):
    if not carry:
        return {}
    out = {}
    for r in db.session.scalars(select(ReviewItem).where(ReviewItem.plan_id == carry["plan"].id,
                                                         ReviewItem.status.in_(("approved", "rejected", "overridden")))):
        if r.target_type == "plan_item" and r.target_key in carry["keys"]:
            out[("plan_item", carry["keys"][r.target_key])] = r
        elif r.target_type == "requirement":
            out[("requirement", r.target_key)] = r
    return out


# --------------------------------------------------------------------------- queue state and assignment

def plan_review_state(plan):
    items = db.session.scalars(select(ReviewItem).where(ReviewItem.plan_id == plan.id)).all()
    open_items = [r for r in items if r.status == "open"]
    run = latest_run(plan)
    blockers = []
    if plan.status in ("generating", "Failed", "superseded"):
        blockers.append(f"The plan is {plan.status.lower()}.")
    if run is None or not run.matrix_approved:
        blockers.append("The plan was validated against a draft matrix. Approve the matrix, then re-validate.")
    if open_items:
        blockers.append(f"{len(open_items)} review item{'s' if len(open_items) != 1 else ''} still need a decision.")
    return {"total": len(items), "open": len(open_items), "decided": len(items) - len(open_items),
            "items": items, "blockers": blockers, "assignable": not blockers and plan.approved_at is None,
            "assigned": plan.approved_at is not None}


def assign_plan(plan, actor):
    state = plan_review_state(plan)
    if state["assigned"]:
        raise ReviewError("This plan is already assigned.")
    if not state["assignable"]:
        raise ReviewError(" ".join(state["blockers"]))
    plan.approved_by, plan.approved_at = (actor or {}).get("email", "system"), utcnow()
    from src.services.progress import start_progress
    tracked = start_progress(plan)
    audit.record("plan.assigned", "plan", plan.plan_code, actor=actor, version=str(plan.version),
                 after={"status": plan.status, "reviewed_items": state["decided"], "tracked_items": tracked}, commit=False)
    db.session.commit()


def queue_counts():
    return dict(db.session.execute(select(ReviewItem.status, func.count()).join(Plan)
                                   .where(Plan.status != "superseded").group_by(ReviewItem.status)).all())


# --------------------------------------------------------------------------- decisions

def _require_reason(reason):
    reason = (reason or "").strip()
    if len(reason) < cfg().get("min_reason_length", 10):
        raise ReviewError(f"Give a reason of at least {cfg().get('min_reason_length', 10)} characters; it is kept in the audit trail.")
    return reason


def _stamp(r, action, actor, reason, new_status=None):
    before = {"status": r.status, "computed_status": r.original_status, "new_status": r.new_status}
    r.status = PAST[action]
    r.new_status = new_status
    r.decision_by, r.decision_at, r.decision_reason = (actor or {}).get("email", "system"), utcnow(), reason
    audit.record(f"review.{r.status}", "review_item", code(r), actor=actor, version=f"{r.plan.plan_code} v{r.plan.version}",
                 before=before, after={"status": r.status, "new_status": new_status, "target": r.target_key},
                 reason=reason, commit=False)


def decide(r, action, actor, form, app_config=None, provider=None):
    """Apply a reviewer decision. Returns (message, plan to show next)."""
    if action not in DECISIONS:
        raise ReviewError("Unknown decision.")
    if r.plan.status == "superseded":
        raise ReviewError("This plan has been replaced by a newer version; decide on the current version.")
    if action == "comment":
        text = (form.get("comment") or "").strip()
        if not text:
            raise ReviewError("Write a comment first.")
        r.comments = r.comments + [{"by": (actor or {}).get("email", "system"),
                                    "at": utcnow().isoformat(timespec="seconds"), "text": text}]
        audit.record("review.commented", "review_item", code(r), actor=actor, reason=text, commit=False)
        db.session.commit()
        return "Comment added.", r.plan
    reason = _require_reason(form.get("reason"))
    if r.status != "open":
        raise ReviewError("This item already has a decision.")

    if action == "approve":
        _stamp(r, action, actor, reason, new_status=r.original_status)
        db.session.commit()
        return "Approved as it is. The computed status is kept next to your decision.", r.plan
    if action == "reject":
        if r.target_type != "plan_item":
            raise ReviewError("A requirement cannot be rejected; approve, override, or regenerate the plan without it / with it.")
        _stamp(r, action, actor, reason, new_status="Rejected")
        db.session.commit()
        return "Rejected. The item will not be shown to the employee.", r.plan
    if action == "override":
        new_status = form.get("new_status")
        if new_status not in cfg()["override_statuses"]:
            raise ReviewError("Choose one of the allowed statuses.")
        _stamp(r, action, actor, reason, new_status=new_status)
        db.session.commit()
        return f"Status overridden to {new_status}. The original status '{r.original_status}' is kept.", r.plan
    if action == "edit":
        return _edit(r, actor, form, reason)
    return _regenerate(r, actor, reason, app_config, provider)


def editable_fields(item):
    """(name, kind, value) for the fields a reviewer may edit: text fields and lists of text."""
    out = []
    for name, value in item.content.items():
        if name in ("requirement_ids", "rubric"):
            continue
        if isinstance(value, str):
            out.append((name, "text", value))
        elif isinstance(value, list) and all(isinstance(v, str) for v in value):
            out.append((name, "lines", "\n".join(value)))
        elif name == "correct_options":
            out.append((name, "indexes", ", ".join(str(v + 1) for v in value)))
    return out


def _edit(r, actor, form, reason):
    if r.target_type != "plan_item" or r.plan_item is None:
        raise ReviewError("Only generated items can be edited.")
    item = r.plan_item
    content = dict(item.content)
    for name, kind, _ in editable_fields(item):
        raw = form.get(f"field__{name}")
        if raw is None:
            continue
        if kind == "text":
            content[name] = raw.strip()
        elif kind == "lines":
            content[name] = [line.strip() for line in raw.splitlines() if line.strip()]
        else:
            try:
                content[name] = [int(v) - 1 for v in raw.replace(" ", "").split(",") if v]
            except ValueError as exc:
                raise ReviewError("Correct options must be numbers such as 1 or 1, 3.") from exc
    try:
        checked = ITEM_SCHEMAS[item.item_type].model_validate(content)
    except ValidationError as exc:
        raise ReviewError("The edited item is not valid: " + "; ".join(e["msg"] for e in exc.errors()[:3])) from exc
    if item.item_type == "quiz_question" and any(i < 0 or i >= len(checked.options) for i in checked.correct_options):
        raise ReviewError("A correct option points at an option that does not exist.")
    diff = {k: {"before": item.content.get(k), "after": content[k]} for k in content if content[k] != item.content.get(k)}
    if not diff:
        raise ReviewError("Nothing was changed.")
    item.content = content
    item.source_doc_id = content.get("source_document_id", item.source_doc_id)
    item.source_section_id = content.get("source_section_id", item.source_section_id)
    if "requirement_id" in diff:
        content["requirement_ids"] = [content["requirement_id"]]
        item.content = dict(content)
        _relink(item, content["requirement_ids"])
    r.edit_diff = diff
    _stamp(r, "edit", actor, reason, new_status=None)
    db.session.flush()

    from src.services.planning import validate_plan          # re-check the whole plan: edits get no free pass
    run = validate_plan(r.plan)
    db.session.flush()
    route_for_review(r.plan, run)
    db.session.commit()
    now = item.status
    if r.status == "open":
        return f"Edit saved and re-validated. Python still reports: {now}. The item is back in the queue.", r.plan
    return f"Edit saved and re-validated. The item is now {now}.", r.plan


def _relink(item, req_ids):
    rows = {x.req_id: x.id for x in db.session.scalars(select(Requirement).where(Requirement.req_id.in_(req_ids)))}
    item.requirement_links = [PlanItemRequirement(requirement_id=rows[rid]) for rid in req_ids if rid in rows]


def _regenerate(r, actor, reason, app_config, provider):
    from src.services.planning import regenerate_modules
    if r.target_type == "plan_item":
        new_plan = regenerate_modules(r.plan, [r.module_key], actor, app_config, reason=reason, provider=provider)
        label = f"module {r.module_key}"
    elif r.original_status == "Requirement Missing":
        new_plan = regenerate_modules(r.plan, [], actor, app_config, reason=reason, provider=provider,
                                      add_requirements=[r.target_key])
        label = f"the module that now covers {r.target_key}"
    elif r.original_status in ("Unsupported Requirement", "Contradiction Detected"):   # does not apply, or lost a conflict
        new_plan = regenerate_modules(r.plan, [], actor, app_config, reason=reason, provider=provider,
                                      drop_requirements=[r.target_key])
        label = f"the module that contained {r.target_key}"
    else:
        raise ReviewError(f"Regenerating does not fix '{r.original_status}' for a requirement the matrix expects; "
                          "approve it or override the status with a reason.")
    _stamp(r, "regenerate", actor, reason, new_status=f"{new_plan.plan_code} v{new_plan.version}")
    db.session.commit()
    if new_plan.status == "Failed":
        return f"Regeneration failed: {new_plan.error}", new_plan
    return (f"Regenerated {label} with Gemini and re-validated the whole plan as v{new_plan.version}: "
            f"{new_plan.status}."), new_plan


def item_for(r):
    return db.session.get(PlanItem, r.plan_item_id) if r.plan_item_id else None


# --------------------------------------------------------------------------- plain-language guidance

def suggestion(r):
    """What the item means in plain words, the recommended decision and a ready-made reason.

    Deterministic wording by status; the reviewer can always change the reason or choose another action.
    """
    from database.models import Document, Requirement
    subject = r.target_key
    doc_title = None
    req = None
    if r.target_type == "requirement":
        req = db.session.scalar(select(Requirement).join(Document).where(
            Requirement.req_id == r.target_key).order_by(Document.status != "active", Requirement.id.desc()))
        if req is not None:
            subject = f"“{req.text}”"
            doc_title = req.document.title
    who = r.plan.employee.name.split(" ")[0]
    role = r.plan.job_role.name
    s = r.original_status
    if s == "Outdated Source":
        return {"meaning": f"The rule {subject} comes from {doc_title or 'a document'} which has passed its review date and "
                           f"has no replacement yet. The rule itself may still be how things are done.",
                "action": "approve", "button": "Keep it: the rule still applies",
                "reason": f"{doc_title or 'The document'} has expired with no replacement yet; the rule is still in force. "
                          f"Keep it and ask the document owner to renew it."}
    if s == "Requirement Missing":
        return {"meaning": f"The approved matrix says {who} ({role}) must learn {subject}, but the generated plan does not "
                           f"include it.",
                "action": "regenerate", "button": "Add it to the plan",
                "reason": f"Required for {role} by the approved matrix; add it to the plan.",
                "fallback": {"action": "approve", "button": "Cover it outside the plan",
                             "reason": f"Not in the generated plan; the trainer will cover it with {who} directly."}}
    if s == "Unsupported Requirement" and r.target_type == "requirement":
        return {"meaning": f"The plan teaches {subject}, but the approved matrix does not assign it to a {role} "
                           f"(or to {who}'s situation).",
                "action": "regenerate", "button": "Remove it from the plan",
                "reason": f"Not required for {role}; remove it to keep the plan focused.",
                "fallback": {"action": "approve", "button": "Keep it as extra reading",
                             "reason": f"Not required for {role}, but harmless awareness content; keeping it."}}
    if s == "Contradiction Detected" and r.target_type == "requirement":
        return {"meaning": f"The plan teaches {subject}, but a reviewer or the precedence rules decided that another "
                           f"document's rule applies instead (see Conflicts). Teaching it would give {who} the overridden version.",
                "action": "regenerate", "button": "Remove it from the plan",
                "reason": "Overridden by the winning rule in a resolved conflict; remove it from the plan.",
                "fallback": {"action": "approve", "button": "Keep it for now",
                             "reason": f"Overridden rule kept for now; the trainer will teach {who} the winning rule instead."}}
    if s in ("Source Support Missing", "Unsupported Requirement"):
        return {"meaning": "This item says something the policy section it cites does not say, or cites no valid "
                           "section. Teaching it could spread a rule that does not exist.",
                "action": "regenerate", "button": "Rewrite this module",
                "reason": "The item is not supported by its cited source; regenerate the module.",
                "fallback": {"action": "reject", "button": "Remove this item",
                             "reason": "Not supported by the cited policy section; removed from the plan."}}
    if s == "Contradiction Detected":
        return {"meaning": "This item follows a rule that a stronger policy overrides, so it teaches the wrong version.",
                "action": "regenerate", "button": "Rewrite this module",
                "reason": "The item follows an overridden rule; regenerate the module from the winning policy.",
                "fallback": {"action": "reject", "button": "Remove this item",
                             "reason": "Contradicts a higher-precedence policy; removed from the plan."}}
    return {"meaning": "Python could not decide this item on its own. Read the source below and decide.",
            "action": "approve", "button": "Approve after checking",
            "reason": "Checked against the cited source; the content is accurate."}


BULK_REASONS = {
    "Outdated Source": "The documents have expired with no replacement yet; the rules are still in force. Keep them and ask the owners to renew the documents.",
    "Requirement Missing": "Not in the generated plan; the trainer will cover these with the employee directly.",
    "Unsupported Requirement": "Not required for this role, but harmless awareness content; keeping them.",
    "Manual Review Required": "Checked against the cited sources; the content is accurate.",
}


def decide_many(items, action, actor, reason):
    """Apply the same approve or reject decision, with one reason, to several open items."""
    if action not in ("approve", "reject"):
        raise ReviewError("Only approve or reject can be applied to several items at once.")
    reason = _require_reason(reason)
    done = 0
    for r in items:
        if r.status != "open" or r.plan.status == "superseded":
            continue
        if action == "reject" and r.target_type != "plan_item":
            continue
        _stamp(r, action, actor, reason, new_status=r.original_status if action == "approve" else "Rejected")
        done += 1
    db.session.commit()
    return done
