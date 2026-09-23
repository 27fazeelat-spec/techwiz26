"""Employee progress, quizzes, manager sign-off and progress status (SRS Steps 53-54).

Progress rows are created when a plan is assigned. Quizzes are scored by Python against the answer
key that validation already checked against the source. Status (On Track, Behind Schedule, ...) is a
rule over due dates and results, configured in config/progress.yaml.
"""
from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select

from config.loader import load_config
from database import audit, db, utcnow
from database.models import Plan, PlanItem, PlanModule, Progress, QuizAttempt, ReviewItem

DONE = ("completed", "waived")


class ProgressError(ValueError):
    pass


def cfg():
    return load_config("progress")


def completion_type(item_type):
    return cfg()["completion"].get(item_type, "none")


def _stage_offsets():
    return {s["code"]: s["day_offset"] for s in load_config("stages")["stages"]}


def assigned_plan(employee):
    """The newest plan version assigned to this employee (it stays in use until a newer one is assigned)."""
    return db.session.scalar(select(Plan).where(Plan.employee_id == employee.id, Plan.approved_at.is_not(None))
                             .order_by(Plan.version.desc()))


def rejected_items(plan):
    return set(db.session.scalars(select(ReviewItem.plan_item_id).where(
        ReviewItem.plan_id == plan.id, ReviewItem.status == "rejected", ReviewItem.plan_item_id.is_not(None))))


def visible_items(plan):
    """(module, item) pairs the employee sees: everything except items a reviewer rejected."""
    hidden = rejected_items(plan)
    return [(m, i) for m in plan.modules for i in m.items if i.id not in hidden]


# --------------------------------------------------------------------------- assignment

def start_progress(plan):
    """Create progress rows for a newly assigned plan, carrying forward work on unchanged items."""
    offsets = _stage_offsets()
    joining = plan.employee.joining_date
    previous = db.session.scalar(select(Plan).where(Plan.plan_code == plan.plan_code, Plan.id != plan.id,
                                                    Plan.approved_at.is_not(None)).order_by(Plan.version.desc()))
    carried = {}
    if previous is not None:
        prefix = f"{previous.plan_code}-v{previous.version}."
        for p in db.session.scalars(select(Progress).where(Progress.plan_id == previous.id)):
            carried[p.plan_item.item_key[len(prefix):]] = p
    new_prefix = f"{plan.plan_code}-v{plan.version}."
    existing = {p.plan_item_id for p in db.session.scalars(select(Progress).where(Progress.plan_id == plan.id))}
    created = 0
    for module, item in visible_items(plan):
        if completion_type(item.item_type) == "none" or item.id in existing:
            continue
        stage = item.stage or module.stage
        due = joining + timedelta(days=offsets.get(stage, 0)) if joining else None
        row = Progress(employee_id=plan.employee_id, plan_id=plan.id, plan_item_id=item.id, due_date=due)
        old = carried.get(item.item_key[len(new_prefix):])
        if old is not None:
            if old.plan_item.content == item.content:
                row.status, row.score, row.attempts = old.status, old.score, old.attempts
                row.submitted_at, row.completed_at, row.verified_by, row.note = (old.submitted_at, old.completed_at,
                                                                                old.verified_by, old.note)
            else:
                row.content_updated = True          # the policy changed this item: the employee redoes it
        db.session.add(row)
        created += 1
    db.session.flush()
    return created


# --------------------------------------------------------------------------- employee actions

def _row(employee, item):
    row = db.session.scalar(select(Progress).where(Progress.employee_id == employee.id, Progress.plan_item_id == item.id))
    if row is None:
        raise ProgressError("This item is not part of your assigned plan.")
    return row


def complete_checklist(employee, item, actor):
    if completion_type(item.item_type) != "employee":
        raise ProgressError("This item is completed by your manager, not ticked off.")
    row = _row(employee, item)
    if row.status in DONE:
        raise ProgressError("Already completed.")
    row.status, row.completed_at, row.content_updated = "completed", utcnow(), False
    audit.record("progress.completed", "plan_item", item.item_key, actor=actor, after={"status": "completed"}, commit=False)
    db.session.commit()


def submit_for_signoff(employee, item, note, actor):
    if completion_type(item.item_type) != "manager" or item.item_type == "assessment":
        raise ProgressError("Only tasks and scenarios are submitted for sign-off.")
    row = _row(employee, item)
    if row.status in DONE or row.status == "submitted":
        raise ProgressError("Already submitted.")
    row.status, row.submitted_at, row.note = "submitted", utcnow(), (note or "").strip() or None
    audit.record("progress.submitted", "plan_item", item.item_key, actor=actor, after={"status": "submitted"}, commit=False)
    db.session.commit()


def quiz_questions(plan, module_key):
    return [i for m, i in visible_items(plan) if m.module_key == module_key and i.item_type == "quiz_question"]


def attempts_used(employee, plan, module_key):
    return db.session.scalar(select(func.count()).select_from(QuizAttempt).where(
        QuizAttempt.employee_id == employee.id, QuizAttempt.plan_id == plan.id, QuizAttempt.module_key == module_key)) or 0


def submit_quiz(employee, plan, module_key, selections, actor):
    """selections: {item_key: [selected option indexes]}. Returns the stored QuizAttempt."""
    questions = quiz_questions(plan, module_key)
    if not questions:
        raise ProgressError("This module has no quiz.")
    used = attempts_used(employee, plan, module_key)
    if used >= cfg()["max_quiz_attempts"]:
        raise ProgressError(f"You have used all {cfg()['max_quiz_attempts']} attempts. Your manager has been asked to review this with you.")
    missing = [q.item_key for q in questions if not selections.get(q.item_key)]
    if missing:
        raise ProgressError(f"Answer every question before submitting ({len(missing)} left).")
    answers, correct = [], 0
    for q in questions:
        chosen = sorted(set(selections[q.item_key]))
        right = sorted(q.content.get("correct_options", []))
        ok = chosen == right
        correct += ok
        answers.append({"item_key": q.item_key, "selected": chosen, "correct": ok,
                        "requirement_id": q.content.get("requirement_id")})
    score = round(100.0 * correct / len(questions), 1)
    passed = score >= cfg()["pass_mark_percent"]
    attempt = QuizAttempt(employee_id=employee.id, plan_id=plan.id, module_key=module_key, attempt_no=used + 1,
                          answers=answers, score=score, passed=passed)
    db.session.add(attempt)
    by_key = {a["item_key"]: a for a in answers}
    for q in questions:
        row = _row(employee, q)
        row.attempts = used + 1
        row.score = 100.0 if by_key[q.item_key]["correct"] else 0.0
        row.status = "completed" if passed else "failed"
        row.completed_at = utcnow() if passed else None
        row.content_updated = False
    audit.record("quiz.submitted", "quiz", f"{plan.plan_code}-v{plan.version}.{module_key}", actor=actor,
                 after={"attempt": used + 1, "score": score, "passed": passed}, commit=False)
    db.session.commit()
    return attempt


# --------------------------------------------------------------------------- manager actions

def sign_off(row, actor, approve, note="", score=None):
    """Manager decision on a submitted task/scenario, or the result of an assessment."""
    item = row.plan_item
    if completion_type(item.item_type) != "manager":
        raise ProgressError("This item is not signed off by a manager.")
    if item.item_type == "assessment":
        if score is None or not (0 <= score <= 100):
            raise ProgressError("Enter the assessment score (0-100) from the rubric.")
        row.score = score
        row.status = "completed" if approve else "failed"
    else:
        if row.status != "submitted":
            raise ProgressError("The employee has not submitted this yet.")
        row.status = "completed" if approve else "in_progress"
    row.note = (note or "").strip() or row.note
    row.verified_by = (actor or {}).get("email", "system")
    row.completed_at = utcnow() if row.status == "completed" else None
    audit.record("progress.signed_off" if approve else "progress.returned", "plan_item", item.item_key, actor=actor,
                 after={"status": row.status, "score": row.score}, reason=note or None, commit=False)
    db.session.commit()


# --------------------------------------------------------------------------- summaries and status

def summary(plan, employee, today):
    rows = {p.plan_item_id: p for p in db.session.scalars(select(Progress).where(
        Progress.plan_id == plan.id, Progress.employee_id == employee.id))}
    by_type, modules = {}, []
    open_due, failed, pending_assessment, other_open, submitted = [], False, 0, 0, 0
    for m in plan.modules:
        tracked = [(i, rows[i.id]) for i in m.items if i.id in rows]
        if not tracked:
            continue
        done = sum(1 for _, r in tracked if r.status in DONE)
        dues = [r.due_date for _, r in tracked if r.due_date and r.status not in DONE]
        quiz = [r for i, r in tracked if i.item_type == "quiz_question"]
        modules.append({"module": m, "done": done, "total": len(tracked),
                        "pct": round(100.0 * done / len(tracked)), "due": min(dues) if dues else None,
                        "quiz_passed": bool(quiz) and all(r.status == "completed" for r in quiz),
                        "quiz_failed": any(r.status == "failed" for r in quiz), "has_quiz": bool(quiz)})
        for i, r in tracked:
            t = by_type.setdefault(i.item_type, {"done": 0, "total": 0})
            t["total"] += 1
            t["done"] += r.status in DONE
            if r.status not in DONE:
                if r.due_date:
                    open_due.append(r.due_date)
                if i.item_type == "assessment":
                    pending_assessment += 1
                else:
                    other_open += 1
                submitted += r.status == "submitted"
            failed = failed or r.status == "failed"
    total = sum(t["total"] for t in by_type.values())
    done = sum(t["done"] for t in by_type.values())
    window = today + timedelta(days=cfg().get("attention_window_days", 2))
    conditions = {
        "Completed": total > 0 and done == total,
        "Behind Schedule": any(d < today for d in open_due),
        "Assessment Required": pending_assessment > 0 and other_open == 0,
        "Requires Attention": failed or any(d <= window for d in open_due),
        "On Track": True,
    }
    status = next(s for s in cfg()["status_order"] if conditions.get(s))
    return {"by_type": by_type, "modules": modules, "done": done, "total": total,
            "pct": round(100.0 * done / total) if total else 0, "status": status, "submitted": submitted,
            "overdue": sum(1 for d in open_due if d < today)}


def pending_signoffs(employees):
    ids = [e.id for e in employees]
    if not ids:
        return []
    return db.session.execute(select(Progress, PlanItem, PlanModule).join(PlanItem, Progress.plan_item_id == PlanItem.id)
                              .join(PlanModule, PlanItem.module_id == PlanModule.id)
                              .where(Progress.employee_id.in_(ids), Progress.status == "submitted")
                              .order_by(Progress.submitted_at)).all()


def weak_requirements(employee, plan):
    """Requirement IDs answered wrongly in any quiz attempt (input for Day 5 recommendations)."""
    wrong = Counter()
    for a in db.session.scalars(select(QuizAttempt).where(QuizAttempt.employee_id == employee.id, QuizAttempt.plan_id == plan.id)):
        for ans in a.answers:
            if not ans["correct"] and ans.get("requirement_id"):
                wrong[ans["requirement_id"]] += 1
    return wrong
