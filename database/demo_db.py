"""The sample workspace for demo visitors ("Saffron Table Kitchens", built by tools/build_demo_db.py).

A demo visitor's requests read a separate SQLite database, never the client's. The committed file is copied to the
temp folder the first time a worker needs it, so the original never changes and every restart starts clean.
SkillSprint's own tables (staff, demo requests, demo accounts, visits) always stay in the main database.
"""
import os
import shutil
import tempfile
import threading
from pathlib import Path

from flask import current_app, g, has_request_context
from sqlalchemy import create_engine

SOURCE = Path(__file__).resolve().parent / "demo" / "saffron_demo.db"
PLATFORM_TABLES = {"platform_staff", "demo_requests", "demo_accounts", "demo_visits"}
SAMPLE_EMPLOYEE = "S001"
ORG_NAME = "Saffron Table Kitchens"
BRAND = {"name": "Saffron Table", "tagline": "Kitchens · a sample workspace", "product_name": "SkillSprint demo",
         "logo": "image/logo.png", "logo_light": "image/logo.png"}
_lock = threading.Lock()


def available():
    return SOURCE.exists()


def active():
    """True while serving a demo visitor's request."""
    return has_request_context() and bool(g.get("demo_db"))


def cache_key():
    return "demo" if active() else "main"


def engine():
    app = current_app._get_current_object()
    eng = app.extensions.get("demo_engine")
    if eng is None:
        with _lock:
            eng = app.extensions.get("demo_engine")
            if eng is None:
                copy = Path(tempfile.gettempdir()) / f"skillsprint-demo-{os.getpid()}-{id(app)}.db"
                shutil.copyfile(SOURCE, copy)
                eng = create_engine("sqlite:///" + str(copy).replace("\\", "/"), connect_args={"check_same_thread": False})
                from database import db                             # tables added after the sample was built
                client = [t for name, t in db.metadata.tables.items() if name not in PLATFORM_TABLES]
                db.metadata.create_all(eng, tables=client, checkfirst=True)
                app.extensions["demo_engine"] = eng
    return eng
