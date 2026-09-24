"""Public pages shown before sign-in: home, platform, trust, about and the demo request form."""
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
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


@bp.route("/demo", methods=["GET", "POST"])
def demo():
    from src.services import demo as demos
    if request.method == "POST":
        try:
            digest = demos.ip_hash(request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip(),
                                   current_app.config["SECRET_KEY"])
            demos.create_request(request.form, digest)
            return redirect(url_for("site.demo_thanks"))
        except demos.DemoError as exc:
            flash(str(exc), "error")
    return render_template("site/demo.html", form=request.form, sizes=demos.SIZES, days=demos.DEMO_DAYS)


@bp.route("/demo/thanks")
def demo_thanks():
    from src.services import demo as demos
    return render_template("site/demo_thanks.html", days=demos.DEMO_DAYS)
