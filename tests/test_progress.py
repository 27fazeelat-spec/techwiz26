"""Progress tracking, quizzes, manager sign-off and progress status (SRS Steps 50, 53-54)."""
from datetime import date, timedelta

import pytest
from flask import current_app
from sqlalchemy import select

from database import db
from database.models import AuditLog, Progress, QuizAttempt, ReviewItem
from src.services import progress, review
from tests.conftest import TODAY, login
from tests.fakes import ScriptedProvider
from tests.test_planning_pipeline import CONFIG, leila
from tests.test_review import ACTOR, REASON, fresh_plan, open_items

MANAGER = {"email": "omar.siddiqui@aurelle.example", "app_role": "manager"}


def assigned(reject_first=False):
    plan = fresh_plan()
    items = open_items(plan)
    for n, r in enumerate(items):
        action = "reject" if reject_first and n == 0 and r.target_type == "plan_item" else "approve"
        review.decide(r, action, ACTOR, REASON)
    review.assign_plan(plan, {"email": "training@aurelle.example"})
    for r in rows(plan):                    # tests share one database: start each plan from scratch
        r.status, r.score, r.attempts, r.completed_at = "not_started", None, 0, None
    db.session.commit()
    return plan


def rows(plan):
    return db.session.scalars(select(Progress).where(Progress.plan_id == plan.id)).all()


def test_assignment_creates_progress_with_due_dates(corpus):
    plan = assigned(reject_first=True)
    tracked = rows(plan)
    rejected = {r.plan_item_id for r in db.session.scalars(select(ReviewItem).where(
        ReviewItem.plan_id == plan.id, ReviewItem.status == "rejected"))}
    types = {r.plan_item.item_type for r in tracked}
    assert tracked and "objective" not in types and not ({r.plan_item_id for r in tracked} & rejected)
    first = tracked[0]
    assert first.due_date >= leila().joining_date and first.status == "not_started"
    assert progress.assigned_plan(leila()).id == plan.id


def test_checklist_and_assessment_rules(corpus):
    plan = assigned()
    me = leila()
    check = next(r.plan_item for r in rows(plan) if r.plan_item.item_type == "checklist")
    progress.complete_checklist(me, check, ACTOR)
    with pytest.raises(progress.ProgressError):
        progress.complete_checklist(me, check, ACTOR)                        # already done
    assessment = next(r for r in rows(plan) if r.plan_item.item_type == "assessment")
    with pytest.raises(progress.ProgressError):
        progress.complete_checklist(me, assessment.plan_item, ACTOR)         # managers assess
    with pytest.raises(progress.ProgressError):
        progress.sign_off(assessment, MANAGER, approve=True)                 # a score is required
    progress.sign_off(assessment, MANAGER, approve=True, score=85)
    assert assessment.status == "completed" and assessment.verified_by == MANAGER["email"]
    assert db.session.scalar(select(AuditLog).where(AuditLog.action == "progress.signed_off"))


def test_quiz_is_scored_by_python_with_a_pass_mark_and_attempt_limit(corpus):
    plan = assigned()
    me = leila()
    module = next(m.module_key for m in plan.modules if progress.quiz_questions(plan, m.module_key))
    questions = progress.quiz_questions(plan, module)
    wrong = {q.item_key: [len(q.content["options"]) - 1] for q in questions}     # the scripted key is option 0
    right = {q.item_key: q.content["correct_options"] for q in questions}
    with pytest.raises(progress.ProgressError):
        progress.submit_quiz(me, plan, module, {}, ACTOR)                    # unanswered
    first = progress.submit_quiz(me, plan, module, wrong, ACTOR)
    assert not first.passed and first.score < progress.cfg()["pass_mark_percent"]
    assert all(r.status == "failed" for r in rows(plan) if r.plan_item in questions)
    second = progress.submit_quiz(me, plan, module, right, ACTOR)
    assert second.passed and second.score == 100.0 and second.attempt_no == 2
    assert all(r.status == "completed" for r in rows(plan) if r.plan_item in questions)
    assert progress.weak_requirements(me, plan)                             # wrong answers are remembered
    progress.submit_quiz(me, plan, module, right, ACTOR)
    with pytest.raises(progress.ProgressError):
        progress.submit_quiz(me, plan, module, right, ACTOR)                # max attempts reached


def test_progress_status_rules(corpus):
    plan = assigned()
    me = leila()
    assert progress.summary(plan, me, TODAY)["status"] == "On Track"          # joins 5 Oct; nothing due yet
    first_due = min(r.due_date for r in rows(plan))
    assert progress.summary(plan, me, first_due - timedelta(days=1))["status"] == "Requires Attention"   # due soon
    assert progress.summary(plan, me, date(2027, 1, 31))["status"] == "Behind Schedule"
    for r in rows(plan):
        if r.plan_item.item_type != "assessment":
            r.status = "completed"
    db.session.commit()
    early = first_due - timedelta(days=progress.cfg()["attention_window_days"] + 3)
    assert progress.summary(plan, me, early)["status"] == "Assessment Required"     # only assessments left
    assert progress.summary(plan, me, date(2027, 1, 31))["status"] == "Behind Schedule"   # ...and now overdue
    for r in rows(plan):
        r.status = "completed"
    db.session.commit()
    s = progress.summary(plan, me, date(2027, 1, 31))
    assert s["status"] == "Completed" and s["pct"] == 100


def test_progress_carries_forward_to_a_regenerated_version(corpus):
    plan = assigned()
    me = leila()
    check = next(r.plan_item for r in rows(plan) if r.plan_item.item_type == "checklist")
    progress.complete_checklist(me, check, ACTOR)
    from src.services.planning import regenerate_modules
    other = next(m.module_key for m in plan.modules if m.module_key != check.module.module_key) \
        if len(plan.modules) > 1 else None
    new = regenerate_modules(plan, [other] if other else [], ACTOR, CONFIG, provider=ScriptedProvider(invent_fact=True))
    for r in open_items(new):
        review.decide(r, "approve", ACTOR, REASON)
    review.assign_plan(new, {"email": "training@aurelle.example"})
    suffix = check.item_key.split(".", 1)[1]
    carried = next(r for r in rows(new) if r.plan_item.item_key.endswith(suffix))
    assert carried.status == "completed"                                     # unchanged item keeps its progress
    assert progress.assigned_plan(me).id == new.id


def test_employee_and_manager_pages(corpus):
    plan = assigned()
    client = current_app.test_client()
    login(client, "leila.haddad@aurelle.example")
    page = client.get("/dashboard/me").data
    assert plan.plan_code.encode() in page
    module = next(m.module_key for m in plan.modules if progress.quiz_questions(plan, m.module_key))
    assert client.get(f"/learn/{module}").status_code == 200
    assert client.get(f"/learn/{module}/quiz").status_code == 200
    questions = progress.quiz_questions(plan, module)
    data = {q.item_key: str(q.content["correct_options"][0]) for q in questions}
    assert b"Passed" in client.post(f"/learn/{module}/quiz", data=data).data
    assert client.get("/team/E001").status_code == 403                       # employees cannot open team pages
    client.post("/logout")
    login(client, "omar.siddiqui@aurelle.example")
    assert b"Leila Haddad" in client.get("/dashboard/team").data
    assert client.get("/team/E001").status_code == 200
    assert client.get("/team/E002").status_code == 403                      # not Omar's report
