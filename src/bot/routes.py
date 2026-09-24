"""Ask the bot (employees) and team questions (line managers). The answering rules are in src/services/bot.py."""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import select

from config.settings import today
from database import audit, db
from database.models import BotQuestion, Employee
from src.rbac import require_permission
from src.services import bot, progress

bp = Blueprint("bot", __name__)


def _asker():
    """(employee, plan, is_demo). Demo visitors ask as the sample company's employee and nothing is stored."""
    from database import demo_db
    if current_user.app_role == "demo":
        if not demo_db.active():
            abort(403)
        code, is_demo = demo_db.SAMPLE_EMPLOYEE, True
    else:
        code, is_demo = current_user.employee_code, False
    employee = db.session.scalar(select(Employee).where(Employee.employee_code == code)) if code else None
    if employee is None:
        abort(403)
    return employee, progress.assigned_plan(employee), is_demo


@bp.route("/ask", methods=["GET", "POST"])
@require_permission("bot.ask")
def ask():
    employee, plan, is_demo = _asker()
    cfg = bot.cfg()
    module_key = (request.values.get("module") or "").strip()[:10] or None
    modules = {m.module_key: m.title for m in plan.modules} if plan else {}
    if module_key not in modules:
        module_key = None
    answer = None
    if request.method == "POST":
        question = (request.form.get("question") or "").strip()
        if len(question) < 3:
            flash("Type a question first.", "error")
        elif is_demo and session.get("bot_asked", 0) >= cfg["demo_limit"]:
            flash(f"The demo allows {cfg['demo_limit']} questions per sign-in.", "info")
        elif not is_demo and bot.asked_today(employee, today(current_app.config)) >= cfg["daily_limit"]:
            flash(f"You have asked {cfg['daily_limit']} questions today. Ask your manager, or try again tomorrow.", "info")
        else:
            actor = audit.actor_from_user(current_user)
            answer = bot.ask(question, employee, actor, current_app.config, module_key=module_key, plan=plan,
                             save=not is_demo)
            if is_demo:
                session["bot_asked"] = session.get("bot_asked", 0) + 1
            else:
                return redirect(url_for("bot.ask", module=module_key, _anchor=f"q-{answer.id}"))
    history = [] if is_demo else db.session.scalars(
        select(BotQuestion).where(BotQuestion.employee_id == employee.id)
        .order_by(BotQuestion.created_at.desc(), BotQuestion.id.desc()).limit(30)).all()
    return render_template("bot/ask.html", employee=employee, plan=plan, modules=modules, module_key=module_key,
                           answer=answer, history=history, is_demo=is_demo, cfg=cfg,
                           has_manager=bool(employee.reporting_manager_code), learner_preview=is_demo)


def _mine(pk):
    employee, _, is_demo = _asker()
    if is_demo:
        abort(403)
    row = db.session.get(BotQuestion, pk)
    if row is None or row.employee_id != employee.id:
        abort(404)
    return row


@bp.route("/ask/<int:pk>/escalate", methods=["POST"])
@require_permission("bot.ask")
def escalate(pk):
    row = _mine(pk)
    if row.status in ("escalated", "manager_answered"):
        return redirect(url_for("bot.ask", _anchor=f"q-{pk}"))
    if bot.escalate(row, audit.actor_from_user(current_user)):
        flash("Sent to your manager. Their reply will appear here.", "success")
    else:
        flash("No line manager is recorded for you. Ask your training manager.", "error")
    return redirect(url_for("bot.ask", _anchor=f"q-{pk}"))


@bp.route("/ask/<int:pk>/feedback", methods=["POST"])
@require_permission("bot.ask")
def feedback(pk):
    row = _mine(pk)
    bot.feedback(row, request.form.get("helpful") == "yes", audit.actor_from_user(current_user))
    return redirect(url_for("bot.ask", _anchor=f"q-{pk}"))


@bp.route("/team/questions")
@require_permission("bot.answer")
def team_questions():
    if not current_user.employee_code:
        abort(403)
    rows = bot.team_questions(current_user.employee_code)
    return render_template("bot/team_questions.html", rows=rows,
                           waiting=sum(r.status == "escalated" for r in rows))


@bp.route("/team/questions/<int:pk>", methods=["POST"])
@require_permission("bot.answer")
def reply(pk):
    row = db.session.get(BotQuestion, pk)
    if row is None or not current_user.employee_code or row.manager_code != current_user.employee_code:
        abort(404)
    text = (request.form.get("reply") or "").strip()
    if len(text) < 2:
        flash("Write a reply first.", "error")
    else:
        bot.manager_reply(row, text, audit.actor_from_user(current_user))
        flash(f"Reply sent to {row.employee.name}.", "success")
    return redirect(url_for("bot.team_questions", _anchor=f"q-{pk}"))
