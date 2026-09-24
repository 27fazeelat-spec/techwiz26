"""Settings the administrator composes: the employee home and which pages each role sees."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
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
