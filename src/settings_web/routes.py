"""Settings the administrator composes: the employee home, which pages each role sees, and staff logins."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from database import audit, db
from src.rbac import require_permission
from src.services import workspace

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/employee-home", methods=["GET", "POST"])
@require_permission("settings.manage")
def employee_home():
    if request.method == "POST":
        try:
            if request.form.get("reset"):
                workspace.reset_employee_home(audit.actor_from_user(current_user))
                flash("The employee home is back to the original layout.", "success")
            else:
                workspace.save_employee_home(request.form, audit.actor_from_user(current_user))
                flash("Saved. Employees see the new home the next time they open it.", "success")
            return redirect(url_for("settings.employee_home"))
        except workspace.SettingsError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("settings/employee_home.html", home=workspace.employee_home(), sections=workspace.SECTIONS,
                           slides=workspace.SLIDES, photos=workspace.photos(), caption=workspace.caption)


@bp.route("/access", methods=["GET", "POST"])
@require_permission("settings.manage")
def pages():
    if request.method == "POST":
        if request.form.get("reset"):
            workspace.reset_pages(audit.actor_from_user(current_user))
            flash("Every role is back to its original pages.", "success")
        else:
            workspace.save_pages(request.form, audit.actor_from_user(current_user))
            flash("Saved. Each role's sidebar now shows the pages you chose; pages you removed cannot be opened either.", "success")
        return redirect(url_for("settings.pages"))
    from config.loader import load_config
    labels = load_config("permissions")["roles"]
    roles = [(r, labels.get(r, {}).get("label", r)) for r in workspace.ROLES]
    grid = []
    for endpoint, label, icon, match, group in workspace.catalog():
        if endpoint.startswith("settings.") or endpoint == "main.admin_dashboard":
            continue
        cells = {}
        for role, _ in roles:
            allowed = workspace._role_can(role, endpoint)
            shown = workspace.pages_for(role)
            cells[role] = {"allowed": allowed, "on": allowed and endpoint in shown,
                           "locked": endpoint in workspace.LOCKED[role],
                           "default": endpoint in workspace.default_pages(role),
                           "needs": workspace.PAGE_PERMISSION.get(endpoint, "")}
        grid.append({"endpoint": endpoint, "label": label, "icon": icon, "group": group, "cells": cells})
    return render_template("settings/pages.html", roles=roles, grid=grid)


@bp.route("/users", methods=["GET", "POST"])
@require_permission("accounts.manage")
def users():
    from database.models import User
    from src.services import users as accounts
    from src.services.demo import MIN_PASSWORD
    if request.method == "POST":
        actor = audit.actor_from_user(current_user)
        action = request.form.get("action")
        try:
            if action == "add":
                user = accounts.add(request.form.get("name"), request.form.get("email"), request.form.get("role"),
                                    request.form.get("password"), request.form.get("manager_code"), actor)
                flash(f"{user.name} can now sign in as {user.email} ({accounts.STAFF_ROLES[user.app_role]}). "
                      "Share the password with them yourself.", "success")
            else:
                user = db.session.get(User, int(request.form.get("id") or 0))
                if user is None or user.app_role == "employee":
                    abort(404)
                if action == "role":
                    accounts.change_role(user, request.form.get("role"), request.form.get("manager_code"), actor)
                    flash(f"{user.name} is now {accounts.STAFF_ROLES[user.app_role]}.", "success")
                elif action == "password":
                    accounts.reset_password(user, request.form.get("password"), actor)
                    flash(f"New password set for {user.email}; any lockout is cleared.", "success")
                elif action in ("on", "off"):
                    accounts.set_active(user, action == "on", actor)
                    flash(f"{user.email} is {'active again' if action == 'on' else 'switched off and signed out'}.", "success")
            return redirect(url_for("settings.users"))
        except accounts.UserError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    people = accounts.staff()
    employees = db.session.scalar(db.select(db.func.count()).select_from(User).where(User.app_role == "employee"))
    return render_template("settings/users.html", people=people, roles=accounts.STAFF_ROLES, me=current_user.email,
                           teams={u.employee_code: accounts.team_size(u.employee_code) for u in people if u.employee_code},
                           employees=employees, min_password=MIN_PASSWORD, form=request.form)
