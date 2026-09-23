"""Authentication. Passwords are stored only as bcrypt hashes; the User table lives in database.models."""
from datetime import timedelta

import bcrypt
from flask_login import UserMixin

from database import db, utcnow
from database.models import User
from src.extensions import login_manager

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


class LoginUser(UserMixin):
    """Session identity. A thin read-only view so request code never holds a stale ORM object."""

    def __init__(self, user):
        self.id = str(user.id)
        self.email = user.email
        self.name = user.name
        self.app_role = user.app_role
        self.employee_code = user.employee_code
        self._active = user.active

    @property
    def is_active(self):
        return self._active


def authenticate(email, password, now=None):
    """Return (LoginUser, error_message). Locks the account for 15 minutes after 5 failed attempts."""
    now = now or utcnow()
    user = db.session.query(User).filter_by(email=(email or "").strip().lower()).first()
    generic = "Email or password is incorrect."
    if user is None or not user.active:
        return None, generic
    if user.locked_until and user.locked_until > now:
        minutes = int((user.locked_until - now).total_seconds() // 60) + 1
        return None, f"Too many failed attempts. Try again in {minutes} minute(s)."
    if not bcrypt.checkpw((password or "").encode(), user.password_hash.encode()):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.failed_logins, user.locked_until = 0, now + LOCKOUT
        db.session.commit()
        return None, generic
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
    db.session.commit()
    return LoginUser(user), None


@login_manager.user_loader
def load_user(user_id):
    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
    return LoginUser(user) if user else None
