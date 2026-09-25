"""Review queue, reviewer decisions, selective regeneration and the assignment gate (SRS Steps 48-49, NFR 4)."""
import pytest
from flask import current_app
from sqlalchemy import select

from database import db
from database.models import AuditLog, Plan, ReviewItem
from src.services import review
from src.services.planning import generate_plan
from tests.conftest import login
from tests.fakes import ScriptedProvider
from tests.test_planning_pipeline import CONFIG, ensure_approved_matrix, leila

ACTOR = {"email": "evaluator@aurelle.example", "app_role": "reviewer"}
REASON = {"reason": "Checked against the approved source"}


def fresh_plan(**kwargs):
    kwargs.setdefault("invent_fact", True)          # one unsupported objective, so there is an item to review
    ensure_approved_matrix()
    return generate_plan(leila(), {"email": "test"}, CONFIG, provider=ScriptedProvider(**kwargs))


def open_items(plan):
    return db.session.scalars(select(ReviewItem).where(ReviewItem.plan_id == plan.id, ReviewItem.status == "open")
                              .order_by(ReviewItem.id)).all()


def test_flagged_items_and_missing_requirements_are_routed(corpus):
    plan = fresh_plan(drop_first_mandatory=True)
    items = open_items(plan)
    routed = set(review.cfg()["route_item_statuses"])
    assert items
    assert all(r.original_status in routed | {"Requirement Missing"} for r in items)
    assert any(r.target_type == "requirement" for r in items)            # the dropped mandatory requirement
    flagged = {i.item_key for m in plan.modules for i in m.items if i.status in routed}
    assert flagged == {r.target_key for r in items if r.target_type == "plan_item"}
    state = review.plan_review_state(plan)
    assert not state["assignable"] and any("still need a decision" in b for b in state["blockers"])


def test_decisions_need_a_reason_and_are_audited(corpus):
    plan = fresh_plan()
    r = open_items(plan)[0]
    with pytest.raises(review.ReviewError):
        review.decide(r, "approve", ACTOR, {"reason": "ok"})
    review.decide(r, "approve", ACTOR, REASON)
    assert r.status == "approved" and r.original_status and r.decision_by == ACTOR["email"]
    entry = db.session.scalar(select(AuditLog).where(AuditLog.action == "review.approved",
                                                     AuditLog.entity_id == review.code(r)))
    assert entry.reason == REASON["reason"] and entry.before["status"] == "open"
    with pytest.raises(review.ReviewError):                             # one decision per item
        review.decide(r, "reject", ACTOR, REASON)


def test_override_keeps_the_computed_status(corpus):
    plan = fresh_plan()
    r = open_items(plan)[0]
    with pytest.raises(review.ReviewError):
        review.decide(r, "override", ACTOR, {**REASON, "new_status": "Totally fine"})
    review.decide(r, "override", ACTOR, {**REASON, "new_status": "Verified"})
    assert r.status == "overridden" and r.new_status == "Verified" and r.original_status != "Verified"


def test_edit_is_schema_checked_and_revalidated(corpus):
    plan = fresh_plan()
    r = next(x for x in open_items(plan) if x.plan_item and x.plan_item.item_type == "objective")
    review.decide(r, "edit", ACTOR, {**REASON, "field__text": "Explain the rules in this module."})
    item = r.plan_item
    assert r.edit_diff["text"]["after"] == "Explain the rules in this module."
    assert item.status not in review.cfg()["route_item_statuses"]        # Python re-checked the edit
    assert r.status == "edited"


def test_invalid_edits_are_refused(corpus):
    plan = fresh_plan()
    quiz = next(i for m in plan.modules for i in m.items if i.item_type == "quiz_question")
    r = ReviewItem(plan_id=plan.id, target_type="plan_item", target_key=quiz.item_key, plan_item=quiz,
                   module_key=quiz.module.module_key, reasons=[], original_status="Manual Review Required", comments=[])
    db.session.add(r)
    db.session.flush()
    with pytest.raises(review.ReviewError):                             # option 9 does not exist
        review.decide(r, "edit", ACTOR, {**REASON, "field__correct_options": "9"})
    with pytest.raises(review.ReviewError):
        review.decide(r, "edit", ACTOR, {**REASON})                     # nothing changed
    db.session.rollback()


def test_adding_a_missing_requirement_regenerates_one_module(corpus):
    plan = fresh_plan(drop_first_mandatory=True)
    items = open_items(plan)
    decided = next(x for x in items if x.target_type == "plan_item")
    review.decide(decided, "reject", ACTOR, REASON)
    missing = next(x for x in items if x.original_status == "Requirement Missing")
    message, new_plan = review.decide(missing, "regenerate", ACTOR, REASON, CONFIG, provider=ScriptedProvider())
    assert new_plan.version == plan.version + 1 and new_plan.parent_plan_id == plan.id
    assert plan.status == "superseded" and missing.status == "regenerated"
    assert missing.target_key in {r["requirement_id"] for r in new_plan.outline["requirements"]}
    assert not db.session.scalar(select(ReviewItem).where(ReviewItem.plan_id == new_plan.id,
                                                          ReviewItem.target_key == missing.target_key))
    regenerated = db.session.scalar(select(AuditLog).where(AuditLog.action == "plan.regenerated")
                                    .order_by(AuditLog.id.desc())).detail["modules"]
    assert len(regenerated) == 1 and len(new_plan.modules) == len(plan.modules)
    carried = db.session.scalar(select(ReviewItem).where(ReviewItem.plan_id == new_plan.id,
                                                         ReviewItem.carried_from_id == decided.id))
    if decided.module_key not in regenerated:                           # copied item: decision carried over
        assert carried is not None and carried.status == "rejected"
    with pytest.raises(review.ReviewError):                             # old version is read-only
        review.decide(next(iter(open_items(plan)), missing), "approve", ACTOR, REASON)


def test_removing_a_wrongly_included_requirement(corpus):
    plan = fresh_plan()
    items = open_items(plan)
    outdated = next((x for x in items if x.target_type == "requirement" and x.original_status == "Outdated Source"), None)
    if outdated is not None:                    # removing a mandatory requirement would only make it missing
        with pytest.raises(review.ReviewError):
            review.decide(outdated, "regenerate", ACTOR, REASON, CONFIG, provider=ScriptedProvider())
        db.session.rollback()
    extra = next(x for x in items if x.target_type == "requirement" and x.original_status == "Unsupported Requirement")
    _, new_plan = review.decide(extra, "regenerate", ACTOR, REASON, CONFIG, provider=ScriptedProvider(invent_fact=True))
    assert extra.target_key not in {r["requirement_id"] for r in new_plan.outline["requirements"]}
    assert not db.session.scalar(select(ReviewItem).where(ReviewItem.plan_id == new_plan.id,
                                                          ReviewItem.target_key == extra.target_key))


def test_plan_is_assignable_only_after_every_decision(corpus):
    plan = fresh_plan()
    with pytest.raises(review.ReviewError):
        review.assign_plan(plan, ACTOR)
    for r in open_items(plan):
        review.decide(r, "approve", ACTOR, REASON)
    review.assign_plan(plan, ACTOR)
    assert plan.approved_at and plan.approved_by == ACTOR["email"]
    assert db.session.scalar(select(AuditLog).where(AuditLog.action == "plan.assigned", AuditLog.entity_id == plan.plan_code))
    with pytest.raises(review.ReviewError):
        review.assign_plan(plan, ACTOR)


def test_review_pages_and_permissions(corpus):
    plan = fresh_plan()
    r = open_items(plan)[0]
    client = current_app.test_client()
    login(client, "training@aurelle.example")
    assert client.get("/review").status_code == 200
    assert client.get(f"/review/{r.id}").status_code == 200
    assert client.post(f"/review/{r.id}/decide", data={"action": "approve", **REASON}).status_code == 403
    client.post("/logout")
    login(client, "evaluator@aurelle.example")
    response = client.post(f"/review/{r.id}/decide", data={"action": "approve", **REASON})
    assert response.status_code == 302
    db.session.refresh(r)
    assert r.status == "approved"
    assert client.get(f"/plans/{plan.id}").status_code == 200
    assert client.post(f"/plans/{plan.id}/assign").status_code == 403      # reviewers decide; managers assign


def test_every_open_item_gets_plain_guidance_and_a_ready_reason(corpus):
    plan = fresh_plan(drop_first_mandatory=True)
    for r in open_items(plan):
        s = review.suggestion(r)
        assert s["meaning"] and s["button"] and len(s["reason"]) >= review.cfg()["min_reason_length"]
        assert s["action"] in ("approve", "regenerate", "reject")


def test_similar_items_can_be_decided_together_with_one_reason(corpus):
    plan = fresh_plan()
    items = open_items(plan)
    with pytest.raises(review.ReviewError):
        review.decide_many(items, "approve", ACTOR, "ok")                   # a real reason is still required
    done = review.decide_many(items, "approve", ACTOR, review.BULK_REASONS["Outdated Source"])
    assert done == len(items) and not open_items(plan)
    assert db.session.scalar(select(AuditLog).where(AuditLog.action == "review.approved")) is not None
    client = current_app.test_client()
    login(client, "evaluator@aurelle.example")
    assert client.get(f"/review?plan={plan.id}&show=decided").status_code == 200


def test_reference_cards_explain_codes_in_plain_words(corpus):
    from database.models import Conflict, Requirement
    client = current_app.test_client()
    login(client, "evaluator@aurelle.example")
    req = db.session.scalar(select(Requirement).where(Requirement.req_id.like("R-GDP-01-%")))
    data = client.get(f"/api/ref/req/{req.req_id}").get_json()
    assert data["title"] == req.text and "Guest" in data["source"] and data["badges"]
    assert client.get("/api/ref/doc/GDP-01").get_json()["title"]
    conflict = db.session.scalar(select(Conflict))
    if conflict:
        assert client.get(f"/api/ref/conflict/{conflict.conflict_code}").get_json()["decision"]
    assert client.get("/api/ref/req/R-NOPE-99-999").status_code == 404
    client.post("/logout")
    login(client, "leila.haddad@aurelle.example")
    assert client.get(f"/api/ref/req/{req.req_id}").status_code == 403


def test_a_rule_that_lost_a_conflict_after_planning_can_be_removed(corpus):
    """A conflict decided after the plan was made: the plan still teaches the losing rule. Remove it cleanly."""
    from database.models import Conflict, Requirement
    from src.services.planning import validate_plan
    from src.services.review import route_for_review
    plan = fresh_plan()
    in_plan = [r["requirement_id"] for r in plan.outline["requirements"]]
    loser = db.session.scalar(select(Requirement).where(Requirement.req_id == in_plan[0]).order_by(Requirement.id.desc()))
    winner = db.session.scalar(select(Requirement).where(Requirement.req_id.notin_(in_plan)).order_by(Requirement.id))
    conflict = Conflict(conflict_code="CF-9901", kind="cross_document", pair_key="test:lost-after-planning",
                        left_requirement_id=loser.id, right_requirement_id=winner.id, differences=[], similarity=1.0,
                        rule_applied="reviewer", winner_requirement_id=winner.id, explanation="Decided by a reviewer.",
                        status="resolved_by_reviewer")
    db.session.add(conflict)
    db.session.commit()
    try:
        route_for_review(plan, validate_plan(plan))
        db.session.commit()
        item = next(x for x in open_items(plan) if x.target_type == "requirement" and x.target_key == loser.req_id)
        assert item.original_status == "Contradiction Detected"
        advice = review.suggestion(item)
        assert advice["action"] == "regenerate" and advice["button"] == "Remove it from the plan"
        _, new_plan = review.decide(item, "regenerate", ACTOR, REASON, CONFIG, provider=ScriptedProvider())
        assert loser.req_id not in {r["requirement_id"] for r in new_plan.outline["requirements"]}
        assert not db.session.scalar(select(ReviewItem).where(ReviewItem.plan_id == new_plan.id,   # not "missing" either
                                                              ReviewItem.target_key == loser.req_id))
    finally:
        db.session.delete(db.session.get(Conflict, conflict.id))            # tests share one database
        db.session.commit()
