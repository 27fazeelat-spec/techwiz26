"""Relational database access: PostgreSQL in deployment, SQLite for local development and tests."""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


def utcnow():
    """Naive UTC timestamp; all DateTime columns store UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ping():
    try:
        db.session.execute(text("SELECT 1"))
        return True
    except Exception:
        db.session.rollback()
        return False


def is_sqlite():
    return db.engine.dialect.name == "sqlite"
