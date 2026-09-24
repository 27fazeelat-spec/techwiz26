"""Relational database access: PostgreSQL in deployment, SQLite for local development and tests."""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.session import Session as FlaskSession
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class RoutingSession(FlaskSession):
    """While a demo visitor is being served, client tables come from the sample database (database/demo_db.py);
    SkillSprint's own tables always come from the main one."""

    def get_bind(self, mapper=None, clause=None, bind=None, **kwargs):
        if bind is None:
            from database import demo_db
            if demo_db.active():
                table = None
                if mapper is not None:
                    try:
                        table = sa_inspect(mapper).local_table.name
                    except Exception:
                        table = None
                if table not in demo_db.PLATFORM_TABLES:
                    return demo_db.engine()
        return super().get_bind(mapper=mapper, clause=clause, bind=bind, **kwargs)


db = SQLAlchemy(model_class=Base, session_options={"class_": RoutingSession})


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


def install_idle_ping(engine, idle_seconds=60):
    """Ping a pooled connection only when it has been idle for a while.

    pool_pre_ping pings on every checkout, which costs one network round trip per request. A pooler
    drops connections after idling, so only those need checking; a dead one is replaced transparently.
    """
    import time
    from sqlalchemy import event, exc

    @event.listens_for(engine, "checkin")
    def _checkin(dbapi_connection, record):
        record.info["idle_since"] = time.monotonic()

    @event.listens_for(engine, "checkout")
    def _checkout(dbapi_connection, record, proxy):
        since = record.info.get("idle_since")
        if since is None or time.monotonic() - since < idle_seconds:
            return
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
        except Exception as error:                  # the pool discards it and opens a fresh connection
            raise exc.DisconnectionError() from error
