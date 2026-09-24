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


# --------------------------------------------------------------------------- weak areas and recommendations

def weak_areas(employee, plan):
    """Requirements and knowledge areas the employee struggles with, from stored quiz answers and task
    returns only (SRS Step 56). Returns [{requirement_id, competency, wrong, text}] worst first."""
    from database.models import Requirement
    wrong = weak_requirements(employee, plan)
    returned = db.session.scalars(select(Progress).join(PlanItem, Progress.plan_item_id == PlanItem.id).where(
        Progress.plan_id == plan.id, Progress.employee_id == employee.id, Progress.status == "in_progress",
        Progress.verified_by.is_not(None))).all()
    for r in returned:
        rid = r.plan_item.content.get("requirement_id")
        if rid:
            wrong[rid] += 1
    if not wrong:
        return []
    rows = {r.req_id: r for r in db.session.scalars(select(Requirement).where(Requirement.req_id.in_(list(wrong))))}
    return [{"requirement_id": rid, "wrong": n, "competency": rows[rid].competency if rid in rows else "",
             "text": rows[rid].text if rid in rows else ""} for rid, n in wrong.most_common()]


def refresh_recommendations(employee, plan, today):
    """Apply the recommendation rules to current signals. Idempotent: one row per rule and module."""
    from database.models import Recommendation
    rules = {k: v for k, v in cfg().get("recommendations", {}).items() if v.get("enabled", True)}
    found = {}                                      # (rule, module) -> signals

    attempts = db.session.scalars(select(QuizAttempt).where(QuizAttempt.employee_id == employee.id,
                                                            QuizAttempt.plan_id == plan.id).order_by(QuizAttempt.attempt_no)).all()
    by_module = {}
    for a in attempts:
        by_module.setdefault(a.module_key, []).append(a)
    for module, tries in by_module.items():
        last, passed = tries[-1], any(t.passed for t in tries)
        if "R-QUIZ-FAIL" in rules and not last.passed:
            found[("R-QUIZ-FAIL", module)] = {"attempt": last.attempt_no, "score": last.score}
        if "R-ATTEMPTS-USED" in rules and not passed and len(tries) >= cfg()["max_quiz_attempts"]:
            found[("R-ATTEMPTS-USED", module)] = {"attempts": len(tries), "best": max(t.score for t in tries)}
        if "R-REPEAT-ERROR" in rules:
            counts = Counter(a["requirement_id"] for t in tries for a in t.answers if not a["correct"] and a.get("requirement_id"))
            repeated = sorted(r for r, n in counts.items() if n >= rules["R-REPEAT-ERROR"].get("min_wrong", 2))
            if repeated:
                found[("R-REPEAT-ERROR", module)] = {"requirements": repeated}
        rule = rules.get("R-FAST-TRACK")
        if rule and tries[0].passed and tries[0].score >= rule.get("min_score", 100) \
                and employee.experience_level in rule.get("levels", []):
            found[("R-FAST-TRACK", module)] = {"score": tries[0].score, "level": employee.experience_level}

    rows = db.session.execute(select(Progress, PlanItem, PlanModule).join(PlanItem, Progress.plan_item_id == PlanItem.id)
                              .join(PlanModule, PlanItem.module_id == PlanModule.id)
                              .where(Progress.plan_id == plan.id, Progress.employee_id == employee.id)).all()
    overdue_days = rules.get("R-OVERDUE", {}).get("min_days", 3)
    late = [r for r, _, _ in rows if r.due_date and r.status not in DONE and (today - r.due_date).days >= overdue_days]
    if "R-OVERDUE" in rules and late:
        found[("R-OVERDUE", "")] = {"items": len(late), "oldest_due": min(r.due_date for r in late).isoformat()}
    for r, item, module in rows:
        if "R-TASK-RETURNED" in rules and item.item_type in ("task", "scenario") and r.status == "in_progress" and r.verified_by:
            found[("R-TASK-RETURNED", module.module_key)] = {"item": item.item_key, "note": r.note}
        if "R-ASSESS-FAIL" in rules and item.item_type == "assessment" and r.status == "failed":
            found[("R-ASSESS-FAIL", module.module_key)] = {"item": item.item_key, "score": r.score}

    existing = {(x.rule_id, x.module_key): x for x in db.session.scalars(select(Recommendation).where(
        Recommendation.employee_id == employee.id, Recommendation.plan_id == plan.id))}
    for (rule_id, module), signals in found.items():
        x = existing.get((rule_id, module))
        if x is None:
            db.session.add(Recommendation(employee_id=employee.id, plan_id=plan.id, rule_id=rule_id, module_key=module,
                                          type=rules[rule_id]["type"], text=rules[rule_id]["text"], signals=signals))
        elif x.status == "open":
            x.signals = signals
    for key, x in existing.items():                 # the signal went away (e.g. the quiz was passed)
        if key not in found and x.status in ("open", "accepted"):
            x.status = "done"
    db.session.commit()
    return db.session.scalars(select(Recommendation).where(Recommendation.employee_id == employee.id,
                                                           Recommendation.plan_id == plan.id,
                                                           Recommendation.status.in_(("open", "accepted")))
                              .order_by(Recommendation.created_at)).all()


def decide_recommendation(rec, accept, actor):
    if rec.status != "open":
        raise ProgressError("This recommendation already has a decision.")
    rec.status = "accepted" if accept else "dismissed"
    rec.decided_by, rec.decided_at = (actor or {}).get("email", "system"), utcnow()
    audit.record(f"recommendation.{rec.status}", "recommendation", f"{rec.rule_id}:{rec.module_key}", actor=actor,
                 after={"type": rec.type}, commit=False)
    db.session.commit()


def overview(plan_ids, today):
    """{plan_id: {"done", "total", "overdue", "pct"}} for many plans in one query (dashboards)."""
    out = {pid: {"done": 0, "total": 0, "overdue": 0, "pct": 0} for pid in plan_ids}
    if not plan_ids:
        return out
    for plan_id, status, due in db.session.execute(select(Progress.plan_id, Progress.status, Progress.due_date)
                                                   .where(Progress.plan_id.in_(list(plan_ids)))):
        o = out[plan_id]
        o["total"] += 1
        if status in DONE:
            o["done"] += 1
        elif due and due < today:
            o["overdue"] += 1
    for o in out.values():
        o["pct"] = round(100 * o["done"] / o["total"]) if o["total"] else 0
    return out


def stages_for(plan, employee, today):
    """Per onboarding stage: items done and total, and whether the stage is past, current or ahead."""
    offsets = _stage_offsets()
    labels = {s["code"]: s["label"] for s in load_config("stages")["stages"]}
    rows = db.session.execute(select(Progress.status, PlanItem.stage, PlanModule.stage)
                              .join(PlanItem, Progress.plan_item_id == PlanItem.id)
                              .join(PlanModule, PlanItem.module_id == PlanModule.id)
                              .where(Progress.plan_id == plan.id, Progress.employee_id == employee.id)).all()
    counts = {}
    for status, item_stage, module_stage in rows:
        c = counts.setdefault(item_stage or module_stage, [0, 0])
        c[1] += 1
        c[0] += status in DONE
    joined = employee.joining_date
    out = []
    for code, offset in offsets.items():
        done, total = counts.get(code, (0, 0))
        due = joined + timedelta(days=offset) if joined else None
        state = "done" if total and done == total else ("due" if due and due <= today else "ahead")
        out.append({"code": code, "label": labels[code], "done": done, "total": total, "due": due, "state": state})
    return out


def up_next(plan, employee, limit=5):
    """The next unfinished items by due date, for the employee's home."""
    return db.session.execute(select(Progress, PlanItem, PlanModule).join(PlanItem, Progress.plan_item_id == PlanItem.id)
                              .join(PlanModule, PlanItem.module_id == PlanModule.id)
                              .where(Progress.plan_id == plan.id, Progress.employee_id == employee.id,
                                     Progress.status.notin_(DONE))
                              .order_by(Progress.due_date, PlanModule.position, PlanItem.position).limit(limit)).all()


# --------------------------------------------------------------------------- completion certificate

def certificate_for(employee, plan):
    from database.models import Certificate
    return db.session.scalar(select(Certificate).where(Certificate.employee_id == employee.id, Certificate.plan_id == plan.id))


def issue_certificate(employee, plan, today, actor):
    """Issue once, only when every tracked item is complete. Returns the Certificate."""
    import secrets
    from database.models import Certificate
    existing = certificate_for(employee, plan)
    if existing:
        return existing
    s = summary(plan, employee, today)
    if s["status"] != "Completed":
        raise ProgressError(f"The certificate is issued when every step is done ({s['done']} of {s['total']} so far).")
    scores = [a.score for a in db.session.scalars(select(QuizAttempt).where(
        QuizAttempt.employee_id == employee.id, QuizAttempt.plan_id == plan.id, QuizAttempt.passed.is_(True)))]
    cert = Certificate(code="AUR-" + secrets.token_hex(4).upper(), employee_id=employee.id, plan_id=plan.id,
                       details={"modules": len(s["modules"]), "items": s["total"],
                                "quiz_average": round(sum(scores) / len(scores), 1) if scores else None,
                                "role": plan.job_role.name, "plan": f"{plan.plan_code} v{plan.version}"})
    db.session.add(cert)
    audit.record("certificate.issued", "certificate", cert.code, actor=actor, after=cert.details, commit=False)
    db.session.commit()
    return cert


def certificate_pdf(cert, brand, logo_path, verify_url):
    """A4 landscape certificate: navy frame, gold rules, the workspace logo and a verification code."""
    import io
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    navy, gold, ink = HexColor("#0E1A33"), HexColor("#C9A45C"), HexColor("#16213B")
    w, h = landscape(A4)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.setTitle(f"Certificate {cert.code}")
    c.setFillColor(HexColor("#FBF8F2")); c.rect(0, 0, w, h, stroke=0, fill=1)
    c.setFillColor(navy); c.rect(0, 0, w, h, stroke=0, fill=0)
    c.setStrokeColor(navy); c.setLineWidth(18); c.rect(9, 9, w - 18, h - 18, stroke=1, fill=0)
    c.setStrokeColor(gold); c.setLineWidth(1.5); c.rect(34, 34, w - 68, h - 68, stroke=1, fill=0)
    c.setLineWidth(0.6); c.rect(40, 40, w - 80, h - 80, stroke=1, fill=0)
    try:
        c.drawImage(logo_path, w / 2 - 34, h - 150, 68, 68, mask="auto")
    except Exception:
        pass
    c.setFillColor(gold); c.setFont("Times-Roman", 13)
    c.drawCentredString(w / 2, h - 172, f"{brand.get('name', '').upper()}  ·  {brand.get('tagline', '').upper()}")
    c.setFillColor(ink); c.setFont("Times-Bold", 38)
    c.drawCentredString(w / 2, h - 228, "Certificate of Onboarding")
    c.setFont("Helvetica", 12); c.setFillColor(HexColor("#6E7385"))
    c.drawCentredString(w / 2, h - 258, "This certifies that")
    c.setFont("Times-BoldItalic", 34); c.setFillColor(navy)
    c.drawCentredString(w / 2, h - 305, cert.employee.name)
    c.setStrokeColor(gold); c.setLineWidth(1); c.line(w / 2 - 170, h - 318, w / 2 + 170, h - 318)
    c.setFont("Helvetica", 12.5); c.setFillColor(ink)
    d = cert.details or {}
    c.drawCentredString(w / 2, h - 344, f"has completed the verified onboarding programme for {d.get('role', '')}")
    c.drawCentredString(w / 2, h - 362, f"at {cert.employee.property.name}: {d.get('modules', 0)} modules and {d.get('items', 0)} checked steps"
                        + (f", quiz average {d['quiz_average']}%." if d.get("quiz_average") is not None else "."))
    c.setFont("Helvetica", 10); c.setFillColor(HexColor("#6E7385"))
    c.drawCentredString(w / 2, h - 384, "Every lesson was checked against the approved policies before it was assigned.")
    y = 92
    c.setFont("Helvetica-Bold", 10.5); c.setFillColor(ink)
    c.drawString(90, y + 16, cert.issued_at.strftime("%d %B %Y")); c.drawRightString(w - 90, y + 16, cert.code)
    c.setStrokeColor(HexColor("#DDD2BF")); c.line(90, y + 10, 270, y + 10); c.line(w - 270, y + 10, w - 90, y + 10)
    c.setFont("Helvetica", 9); c.setFillColor(HexColor("#6E7385"))
    c.drawString(90, y - 2, "Date issued"); c.drawRightString(w - 90, y - 2, "Verification code")
    c.drawCentredString(w / 2, 62, f"Verify at {verify_url}  ·  Powered by SkillSprint")
    c.showPage(); c.save()
    return buf.getvalue()
