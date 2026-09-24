"""Authentication. Passwords are stored only as bcrypt hashes.

Three kinds of account sign in through the same page:
* workspace users (database.models.User): the client's administrator, trainers, reviewers, managers, employees;
* SkillSprint staff (PlatformStaff): the console only, never a client workspace; session id "s:<id>";
* demo visitors (DemoAccount): read-only, until the account's expiry date; session id "d:<id>".
"""
from datetime import timedelta

import bcrypt
from flask_login import UserMixin

from database import db, utcnow
from database.models import DemoAccount, PlatformStaff, User
from src.extensions import login_manager

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


class LoginUser(UserMixin):
    """Session identity. A thin read-only view so request code never holds a stale ORM object."""

    def __init__(self, user, prefix="", app_role=None):
        self.id = f"{prefix}{user.id}"
        self.email = user.email
        self.name = user.name
        self.app_role = app_role or user.app_role
        self.employee_code = getattr(user, "employee_code", None)
        self.expires_at = getattr(user, "expires_at", None)
        self.company = getattr(user, "company", "")
        self._active = user.active

    @property
    def is_active(self):
        return self._active

    @property
    def days_left(self):
        if self.expires_at is None:
            return None
        return max(0, (self.expires_at - utcnow()).days + (1 if (self.expires_at - utcnow()).seconds else 0))


def _identity(account):
    if isinstance(account, PlatformStaff):
        return LoginUser(account, "s:", "platform_admin")
    if isinstance(account, DemoAccount):
        return LoginUser(account, "d:", "demo")
    return LoginUser(account)


def authenticate(email, password, now=None):
    """Return (LoginUser, error_message). Locks the account for 15 minutes after 5 failed attempts."""
    now = now or utcnow()
    email = (email or "").strip().lower()
    generic = "Email or password is incorrect."
    account = (db.session.query(User).filter_by(email=email).first()
               or db.session.query(PlatformStaff).filter_by(email=email).first()
               or db.session.query(DemoAccount).filter_by(email=email).first())
    if account is None or not account.active:
        return None, generic
    if account.locked_until and account.locked_until > now:
        minutes = int((account.locked_until - now).total_seconds() // 60) + 1
        return None, f"Too many failed attempts. Try again in {minutes} minute(s)."
    if not bcrypt.checkpw((password or "").encode(), account.password_hash.encode()):
        account.failed_logins += 1
        if account.failed_logins >= MAX_FAILED_LOGINS:
            account.failed_logins, account.locked_until = 0, now + LOCKOUT
        db.session.commit()
        return None, generic
    if isinstance(account, DemoAccount) and account.expires_at <= now:
        return None, "Your demo has ended. Contact SkillSprint to continue."
    account.failed_logins, account.locked_until, account.last_login_at = 0, None, now
    if isinstance(account, DemoAccount):
        account.login_count = (account.login_count or 0) + 1
    db.session.commit()
    return _identity(account), None


@login_manager.user_loader
def load_user(user_id):
    user_id = str(user_id or "")
    model = PlatformStaff if user_id.startswith("s:") else DemoAccount if user_id.startswith("d:") else User
    try:
        account = db.session.get(model, int(user_id.split(":")[-1]))
    except (TypeError, ValueError):
        return None
    if account is None:
        return None
    if isinstance(account, DemoAccount) and (not account.active or account.expires_at <= utcnow()):
        return None                                               # an ended demo signs out on its next page
    return _identity(account)
