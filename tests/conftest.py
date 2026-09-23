import csv
import os
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "sample_documents"
DATASET = ROOT / "documentation" / "dataset"
TODAY = date(2026, 9, 23)   # the dataset's reference date

# In-memory SQLite by default. Set TEST_DATABASE_URL to run the same suite against a real PostgreSQL
# database - use a dedicated, empty test database: every test drops and recreates all tables.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite://")
TEST_CONFIG = {"TESTING": True, "SQLALCHEMY_DATABASE_URI": TEST_DATABASE_URL, "WTF_CSRF_ENABLED": False,
               "TODAY_OVERRIDE": TODAY.isoformat(), "SECRET_KEY": "test"}


def read_register(name):
    with open(DATASET / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def sample_files():
    return sorted(p for p in SAMPLES.iterdir() if p.suffix in (".pdf", ".docx"))


def _guard_against_real_data(app):
    """Refuse to wipe a database that holds real data. Tests drop every table, so they may only
    run against in-memory SQLite or a dedicated, empty test database that is not DATABASE_URL."""
    from sqlalchemy import inspect, text
    from config.settings import database_url
    from database import db
    url = app.config["SQLALCHEMY_DATABASE_URI"]
    if url == "sqlite://":
        return
    main_url = os.getenv("DATABASE_URL", "").strip()
    if main_url and database_url(main_url) == url:
        pytest.exit("TEST_DATABASE_URL points at the app's main DATABASE_URL. Refusing to drop its tables; "
                    "use a separate, empty test database.", returncode=2)
    if "documents" in inspect(db.engine).get_table_names():
        docs = db.session.execute(text("SELECT COUNT(*) FROM documents WHERE uploaded_by <> 'pytest'")).scalar()
        if docs:
            pytest.exit(f"The test database contains {docs} real document(s). Refusing to drop its tables.",
                        returncode=2)


def _make_app():
    from database import db
    from src import create_app
    app = create_app(dict(TEST_CONFIG))
    with app.app_context():       # start every app from empty tables (matters for PostgreSQL)
        _guard_against_real_data(app)
        db.drop_all()
        db.create_all()
    return app


@pytest.fixture()
def app():
    app = _make_app()
    with app.app_context():
        from src.cli import seed_database
        seed_database(password="correct-horse")
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, email, password="correct-horse"):
    from flask import g, has_app_context
    if has_app_context():               # tests inside one app context share flask.g: drop the previous user
        g.pop("_login_user", None)
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=False)


@pytest.fixture(scope="session")
def corpus():
    """All sample documents ingested once into an in-memory database. Yields (session, results)."""
    app = _make_app()
    with app.app_context():
        from database import db
        from src.cli import ingest_folder_files, seed_database
        seed_database(password="correct-horse")          # roles must exist for role mapping
        results = {path.name: result for path, result in
                   ingest_folder_files(SAMPLES, TODAY, actor={"email": "pytest", "app_role": "test"})}
        yield db.session, results
