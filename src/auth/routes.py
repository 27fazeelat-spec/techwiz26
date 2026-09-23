from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from flask_wtf import FlaskForm
from wtforms import EmailField, PasswordField
from wtforms.validators import DataRequired

from database import audit
from src.auth.models import authenticate

bp = Blueprint("auth", __name__)


class LoginForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])


def _safe_next(target):
    """Only allow redirects within this site."""
    if target and not urlparse(target).netloc and target.startswith("/"):
        return target
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    form = LoginForm()
    if form.validate_on_submit():
        user, error = authenticate(form.email.data, form.password.data)
        if user:
            login_user(user)
            audit.record("user.login", "user", user.id, actor=audit.actor_from_user(user))
            return redirect(_safe_next(request.args.get("next")) or url_for("main.home"))
        audit.record("user.login_failed", "user", (form.email.data or "").lower(),
                     detail={"ip": request.remote_addr})
        flash(error, "error")
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
def logout():
    if current_user.is_authenticated:
        audit.record("user.logout", "user", current_user.id, actor=audit.actor_from_user(current_user))
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
