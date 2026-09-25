"""Workspace staff logins the administrator manages: training managers, reviewers, line managers, administrators.

Employees get their login on the employee form (src/services/people.py); this is for everyone else.
Guardrails: an email belongs to one account only, passwords have at least 10 characters and are stored as hashes,
a line manager has a manager code that employees are linked to, nobody changes or switches off their own login, and
at least one active administrator always remains. Every change is recorded in the audit trail.
"""
import re

from sqlalchemy import func, select

from database import audit, db
from database.models import Employee, Organization, User
from src.services.demo import EMAIL, MIN_PASSWORD, email_in_use

STAFF_ROLES = {"training_manager": "Training Manager", "reviewer": "Reviewer", "manager": "Line manager",
               "admin": "Administrator"}
CODE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,19}$")


class UserError(ValueError):
    pass


def staff():
    return db.session.scalars(select(User).where(User.app_role != "employee")
                              .order_by(User.active.desc(), User.app_role, User.name)).all()


def managers():
    """(code, name) of active line managers, for the employee form."""
    return db.session.execute(select(User.employee_code, User.name).where(
        User.app_role == "manager", User.active.is_(True), User.employee_code.is_not(None)).order_by(User.name)).all()


def team_size(code):
    return db.session.scalar(select(func.count()).select_from(Employee).where(Employee.reporting_manager_code == code)) or 0


def _password(password):
    if len(password or "") < MIN_PASSWORD:
        raise UserError(f"The password needs at least {MIN_PASSWORD} characters.")


def _code(role, code, user=None):
    if role != "manager":
        return None
    code = (code or "").strip().upper()
    if not CODE.match(code):
        raise UserError("A line manager needs a manager code such as M002 (letters, digits and dashes).")
    taken = db.session.scalar(select(User).where(User.employee_code == code))
    if (taken and taken is not user) or db.session.scalar(select(Employee.id).where(Employee.employee_code == code)):
        raise UserError(f"The code {code} is already used by someone else.")
    return code


def _other_admins(user):
    return db.session.scalar(select(func.count()).select_from(User).where(
        User.app_role == "admin", User.active.is_(True), User.id != user.id)) or 0


def _not_me(user, actor, what):
    if actor and user.email == actor.get("email"):
        raise UserError(f"You cannot {what} your own login.")


def add(name, email, role, password, code, actor):
    from src.auth.models import hash_password
    name, email = " ".join((name or "").split())[:200], (email or "").strip().lower()
    if not name:
        raise UserError("Enter the person's name.")
    if not EMAIL.match(email):
        raise UserError("Enter a valid email address.")
    if role not in STAFF_ROLES:
        raise UserError("Choose a role.")
    if email_in_use(email):
        raise UserError("An account with this email already exists.")
    _password(password)
    code = _code(role, code)
    org = db.session.scalar(select(Organization.id))
    user = User(organization_id=org, email=email, name=name, app_role=role, employee_code=code,
                password_hash=hash_password(password))
    db.session.add(user)
    audit.record("user.created", "user", email, actor=actor, after={"role": role, "manager_code": code}, commit=False)
    db.session.commit()
    return user


def change_role(user, role, code, actor):
    if user.app_role == "employee" or role not in STAFF_ROLES:
        raise UserError("Choose a role.")
    _not_me(user, actor, "change the role of")
    if user.app_role == "admin" and role != "admin" and user.active and not _other_admins(user):
        raise UserError("At least one active administrator must remain.")
    before = {"role": user.app_role, "manager_code": user.employee_code}
    if role == "manager":
        user.employee_code = _code(role, code or user.employee_code, user)
    elif user.app_role == "manager" and team_size(user.employee_code):
        raise UserError(f"{user.name} is still the line manager of {team_size(user.employee_code)} employee(s). "
                        "Give them another manager on the employee form first.")
    else:
        user.employee_code = None
    user.app_role = role
    audit.record("user.role_changed", "user", user.email, actor=actor, before=before,
                 after={"role": role, "manager_code": user.employee_code}, commit=False)
    db.session.commit()


def reset_password(user, password, actor):
    from src.auth.models import hash_password
    _password(password)
    user.password_hash, user.failed_logins, user.locked_until = hash_password(password), 0, None
    audit.record("user.password_reset", "user", user.email, actor=actor, commit=False)
    db.session.commit()


def set_active(user, active, actor):
    if not active:
        _not_me(user, actor, "switch off")
        if user.app_role == "admin" and not _other_admins(user):
            raise UserError("At least one active administrator must remain.")
    user.active = active
    audit.record("user.switched_on" if active else "user.switched_off", "user", user.email, actor=actor, commit=False)
    db.session.commit()
