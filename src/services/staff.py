"""SkillSprint staff who use the console: add, reset a password, switch off or back on.

Guardrails: an email belongs to one account only (client user, staff or demo), passwords have at least 10
characters and are stored as hashes, nobody can switch themselves off, and at least one staff login stays active.
"""
from sqlalchemy import func, select

from database import audit, db
from database.models import PlatformStaff
from src.services.demo import EMAIL, MIN_PASSWORD, email_in_use


class StaffError(ValueError):
    pass


def all_staff():
    return db.session.scalars(select(PlatformStaff).order_by(PlatformStaff.active.desc(), PlatformStaff.name)).all()


def _check_password(password):
    if len(password or "") < MIN_PASSWORD:
        raise StaffError(f"The password needs at least {MIN_PASSWORD} characters.")


def add(name, email, password, actor):
    from src.auth.models import hash_password
    name, email = " ".join((name or "").split())[:200], (email or "").strip().lower()
    if not name:
        raise StaffError("Enter the person's name.")
    if not EMAIL.match(email):
        raise StaffError("Enter a valid email address.")
    if email_in_use(email):
        raise StaffError("An account with this email already exists.")
    _check_password(password)
    person = PlatformStaff(email=email, name=name, password_hash=hash_password(password))
    db.session.add(person)
    audit.record("console.staff_added", "platform_staff", email, actor=actor, after={"name": name}, commit=False)
    db.session.commit()
    return person


def reset_password(person, password, actor):
    from src.auth.models import hash_password
    _check_password(password)
    person.password_hash, person.failed_logins, person.locked_until = hash_password(password), 0, None
    audit.record("console.staff_password_reset", "platform_staff", person.email, actor=actor, commit=False)
    db.session.commit()


def set_active(person, active, actor):
    if not active:
        if actor and person.email == actor.get("email"):
            raise StaffError("You cannot switch off your own login.")
        others = db.session.scalar(select(func.count()).select_from(PlatformStaff)
                                   .where(PlatformStaff.active.is_(True), PlatformStaff.id != person.id)) or 0
        if others == 0:
            raise StaffError("At least one staff login must stay active.")
    person.active = active
    audit.record("console.staff_on" if active else "console.staff_off", "platform_staff", person.email, actor=actor,
                 commit=False)
    db.session.commit()
