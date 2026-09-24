"""Public pages shown before sign-in: home, platform, trust and about."""
from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user

bp = Blueprint("site", __name__)

# Figures measured on the Aurelle sample collection (see reports/ and the test suite); nothing here is invented.
MEASURED = {"recall": 99.5, "precision": 100, "attacks": 12, "conflicts": 12, "documents": 44, "requirements": 185,
            "roles": 10, "rules": 17, "tests": 129}


@bp.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    return render_template("site/home.html", m=MEASURED)


@bp.route("/platform")
def platform():
    return render_template("site/platform.html", m=MEASURED)


@bp.route("/trust")
def trust():
    return render_template("site/trust.html", m=MEASURED)


@bp.route("/about")
def about():
    return render_template("site/about.html", m=MEASURED)
