"""Plan tidy-up: items due at their requirement's stage, checklists only for actions, one item per action."""
from sqlalchemy import select

from database import db
from database.models import MatrixRow, Progress, Requirement
from src.services import staging
from tests.test_review import fresh_plan


def _matrix_stages(plan):
    return dict(db.session.execute(
        select(Requirement.req_id, MatrixRow.due_stage).join(Requirement, MatrixRow.requirement_id == Requirement.id)
        .where(MatrixRow.matrix_version_id == plan.matrix_version_id, MatrixRow.job_role_id == plan.job_role_id)).all())


def test_every_item_is_due_at_its_requirements_stage(corpus):
    plan = fresh_plan()
    stages = _matrix_stages(plan)
    order = {"D1": 0, "W1": 1, "W2": 2, "D30": 3, "D60": 4, "D90": 5}
    for m in plan.modules:
        module_reqs = [r["requirement_id"] for r in plan.outline["requirements"] if r["module_key"] == m.module_key]
        for i in m.items:
            ids = [r for r in i.content.get("requirement_ids", []) if r in stages]
            if i.item_type == "assessment" and module_reqs:
                assert i.stage == max((stages[r] for r in module_reqs if r in stages), key=order.get)
            elif ids and i.item_type != "assessment":
                assert i.stage == min((stages[r] for r in ids), key=order.get)       # not the module's earliest stage


def test_working_rules_leave_the_checklist_and_duplicates_merge(corpus):
    plan = fresh_plan()
    checklist = [i for m in plan.modules for i in m.items if i.item_type == "checklist"]
    taught = {r for m in plan.modules for i in m.items if i.item_type in ("quiz_question", "task", "scenario")
              for r in i.content.get("requirement_ids", [])}
    rule = next(r for r in sorted(taught) if (lambda q: q and q.req_type == "Must Know" and not staging.PASSIVE_ACTION.search(q.text))(
        db.session.scalar(select(Requirement).where(Requirement.req_id == r).order_by(Requirement.id.desc()))))
    working = checklist[-1]
    working.content = {**working.content, "activity": "Apply the room key rules correctly at the desk", "requirement_ids": [rule]}
    first, second = [i for i in checklist if i is not working][:2]
    second.stage = first.stage
    first.content = {**first.content, "activity": "Complete the fire and life safety orientation"}
    second.content = {**second.content, "activity": "Attend fire and life safety orientation on the first day"}
    db.session.flush()
    for i in (first, second):                 # keep both at the same stage so they count as the same action
        i.content = {**i.content, "requirement_ids": first.content["requirement_ids"]}
    db.session.flush()

    preview = staging.tidy(plan, dry_run=True)
    assert any(working.item_key in d for d in preview["dropped"]) and any(second.item_key in m for m in preview["merged"])
    assert db.session.get(type(working), working.id) is not None               # a dry run changes nothing

    keys = {working.item_key, second.item_key}
    staging.tidy(plan)
    db.session.refresh(plan)
    left = {i.item_key for m in plan.modules for i in m.items}
    assert not keys & left and first.item_key in left
    assert "also_cited" in db.session.get(type(first), first.id).content


def test_work_already_started_is_never_removed(corpus):
    from tests.test_progress import assigned
    plan = assigned()
    rows = db.session.scalars(select(Progress).where(Progress.plan_id == plan.id)).all()
    done = next(r for r in rows if r.plan_item.item_type == "checklist")
    done.status = "completed"
    db.session.commit()
    item_id = done.plan_item_id
    staging.tidy(plan)
    db.session.commit()
    assert db.session.get(Progress, done.id) is not None and db.session.get(type(done.plan_item), item_id) is not None
    for r in db.session.scalars(select(Progress).where(Progress.plan_id == plan.id, Progress.status == "not_started")):
        assert r.due_date is not None
