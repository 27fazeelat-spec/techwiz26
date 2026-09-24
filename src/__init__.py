"""SkillSprint AI - Flask application factory."""
from pathlib import Path

from urllib.parse import urlsplit

from flask import Flask, render_template
from sqlalchemy.exc import InterfaceError, OperationalError

from config.loader import load_config, validate_all
from config.settings import Settings, database_url, engine_options
from database import db, is_sqlite
from src.extensions import csrf, login_manager


def _connection_help(url, exc):
    """A readable startup error that never includes the password."""
    parts = urlsplit(url)
    message = (f"Cannot connect to the database at {parts.hostname}:{parts.port or 5432} "
               f"({type(exc.orig).__name__ if getattr(exc, 'orig', None) else type(exc).__name__}).")
    if "CERTIFICATE_VERIFY_FAILED" in str(exc):
        message += (" The server's TLS certificate could not be verified. Set DATABASE_SSL_ROOT_CERT to the "
                    "provider's CA certificate file (Supabase: Project Settings > Database > SSL Configuration).")
    elif parts.hostname and parts.hostname.startswith("db.") and parts.hostname.endswith(".supabase.co"):
        message += (" Supabase direct-connection hosts are IPv6-only. On an IPv4 network, use the "
                    "Session pooler connection string (Supabase dashboard > Connect > Session pooler).")
    else:
        message += " Check DATABASE_URL, network access and that the database server is running."
    return message


def create_app(overrides=None):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(Settings)
    if overrides:
        app.config.update(overrides)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url(app.config["SQLALCHEMY_DATABASE_URI"])
    app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", engine_options(app.config["SQLALCHEMY_DATABASE_URI"]))

    validate_all()   # refuse to start with a broken config
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///"):
        Path(app.config["SQLALCHEMY_DATABASE_URI"][len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)

    import database.models  # noqa: F401  (registers the tables)
    with app.app_context():
        if db.engine.dialect.name == "postgresql":
            from database import install_idle_ping
            install_idle_ping(db.engine)
            # pg8000's executemany sends one statement per row (a network round trip each). Let SQLAlchemy
            # render many-row INSERTs as one multi-VALUES statement instead, as it already does when a
            # primary key is returned.
            db.engine.dialect.use_insertmanyvalues_wo_returning = True
        try:
            db.create_all()
        except (OperationalError, InterfaceError) as exc:
            raise RuntimeError(_connection_help(app.config["SQLALCHEMY_DATABASE_URI"], exc)) from None

    from src.auth.routes import bp as auth_bp
    from src.documents.routes import bp as documents_bp
    from src.ground_truth.routes import bp as ground_truth_bp
    from src.main.routes import bp as main_bp
    from src.plans.routes import bp as plans_bp
    from src.review.routes import bp as review_bp
    from src.changes.routes import bp as changes_bp
    from src.learning.routes import bp as learning_bp
    from src.people.routes import bp as people_bp
    from src.reports_web.routes import bp as reports_bp
    from src.site.routes import bp as site_bp
    from src.api.routes import bp as api_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(ground_truth_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(changes_bp)
    app.register_blueprint(learning_bp)
    app.register_blueprint(people_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(site_bp)
    app.register_blueprint(api_bp)

    from src import ui_text
    ui_text.register(app)

    from src.cli import bootstrap_local, register_cli
    register_cli(app)
    if not app.config.get("TESTING"):
        with app.app_context():
            if is_sqlite():
                bootstrap_local(app)

    from src.rbac import has_permission

    @app.context_processor
    def template_helpers():
        from flask_login import current_user
        from database.models import Organization
        if "org_name" not in app.extensions:            # it rarely changes: read it once (settings page clears it)
            org = db.session.query(Organization.name, Organization.settings).first()
            if org is None:
                return {"can": lambda perm: has_permission(current_user, perm), "org_name": "No organisation set up",
                        "brand": dict(load_config("branding")),
                        "role_label": lambda code: load_config("permissions")["roles"].get(code, {}).get("label", code)}
            app.extensions["org_name"] = org.name
            app.extensions["brand"] = {**load_config("branding"), **((org.settings or {}).get("branding") or {})}
        roles = load_config("permissions")["roles"]
        def ref_documents():
            from src.api.routes import known_documents
            return known_documents() if current_user.is_authenticated else []
        return {
            "ref_documents": ref_documents,
            "can": lambda perm: has_permission(current_user, perm),
            "org_name": app.extensions["org_name"],
            "brand": app.extensions["brand"],
            "role_label": lambda code: roles.get(code, {}).get("label", code),
        }

    @app.teardown_request
    def rollback_on_error(exc):
        if exc is not None:
            db.session.rollback()

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(_):
        return render_template("errors/413.html", limit=app.config["MAX_UPLOAD_MB"]), 413

    return app
