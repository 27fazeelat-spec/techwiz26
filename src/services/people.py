"""Job roles and employee profiles (SRS FR iii-iv, Step 9; integrity challenge 3: a hidden role).

A new role starts as 'pending_mapping'. Its requirements are found by the same rules the matrix uses
(role name, aliases, department, document audience), previewed here, and only take effect after the
role is activated and a new matrix is built and approved by a person. No sensitive personal data
(national ID, salary, health) is stored or asked for.
"""
import re
from datetime import date

from sqlalchemy import select

from database import audit, db
from database.models import Chunk, Document, Employee, JobRole, Organization, Property, Requirement
from role_matrix.applicability import resolve_roles

CODE = re.compile(r"^[A-Z]{2,6}$")
EMPLOYEE_CODE = re.compile(r"^[A-Z]\d{3,6}$")
LEVELS = ("Beginner", "Intermediate", "Advanced")
SHIFTS = ("day", "night", "rotating")


class PeopleError(ValueError):
    pass


def _aliases(text):
    return [a.strip() for a in (text or "").split(",") if a.strip()]


def _org_id():
    return db.session.scalar(select(Organization.id))


# --------------------------------------------------------------------------- roles

def create_role(code, name, department, aliases, actor):
    code, name, department = (code or "").strip().upper(), (name or "").strip(), (department or "").strip()
    if not CODE.match(code):
        raise PeopleError("The role code must be 2 to 6 capital letters, e.g. NAU.")
    if not name or not department:
        raise PeopleError("Give the role a name and a department.")
    if db.session.scalar(select(JobRole).where((JobRole.code == code) | (JobRole.name == name))):
        raise PeopleError("A role with this code or name already exists.")
    role = JobRole(organization_id=_org_id(), code=code, name=name, department=department,
                   aliases=_aliases(aliases), status="pending_mapping")
    db.session.add(role)
    audit.record("role.created", "job_role", code, actor=actor, after={"name": name, "department": department,
                                                                      "aliases": role.aliases}, commit=False)
    db.session.commit()
    return role


def update_role(role, name, department, aliases, actor):
    before = {"name": role.name, "department": role.department, "aliases": role.aliases}
    name, department = (name or "").strip(), (department or "").strip()
    if not name or not department:
        raise PeopleError("Give the role a name and a department.")
    clash = db.session.scalar(select(JobRole).where(JobRole.name == name, JobRole.id != role.id))
    if clash:
        raise PeopleError("Another role already has this name.")
    role.name, role.department, role.aliases = name, department, _aliases(aliases)
    audit.record("role.updated", "job_role", role.code, actor=actor, before=before,
                 after={"name": role.name, "department": role.department, "aliases": role.aliases}, commit=False)
    db.session.commit()


def preview_mapping(role):
    """Requirements this role would receive in the next matrix: role-specific ones and those for everyone."""
    roles = db.session.scalars(select(JobRole).where(JobRole.status == "active", JobRole.id != role.id)).all() + [role]
    rows = db.session.execute(
        select(Requirement, Document, Chunk).join(Document, Requirement.document_id == Document.id)
        .join(Chunk, Requirement.chunk_id == Chunk.id)
        .where(Document.status.in_(["active", "expired"]), Document.tier > 0,
               Requirement.review_status != "rejected", Chunk.quarantined.is_(False))
        .order_by(Requirement.doc_id, Requirement.position)).all()
    specific, everyone = [], 0
    for req, doc, chunk in rows:
        codes = req.roles if req.review_status == "edited" else resolve_roles(
            req.subject, chunk.heading_path, doc.applies_to_text, roles)
        if codes == ["ALL"]:
            everyone += 1
        elif role.code in codes:
            specific.append(req)
    return {"specific": specific, "everyone": everyone, "mandatory": sum(r.mandatory for r in specific),
            "documents": sorted({r.doc_id for r in specific})}


def activate_role(role, actor):
    if role.status == "active":
        raise PeopleError("The role is already active.")
    preview = preview_mapping(role)
    role.status = "active"
    audit.record("role.activated", "job_role", role.code, actor=actor,
                 after={"role_specific_requirements": len(preview["specific"]), "for_everyone": preview["everyone"]},
                 commit=False)
    db.session.commit()
    return preview


# --------------------------------------------------------------------------- employees

def _employee_fields(form):
    """Validate the Step 9 profile fields. Returns a dict ready for the Employee model."""
    errors = []
    name = (form.get("name") or "").strip()
    if len(name) < 2:
        errors.append("Enter the employee's name.")
    role = db.session.scalar(select(JobRole).where(JobRole.code == form.get("role_code"), JobRole.status == "active"))
    if role is None:
        errors.append("Choose an active job role.")
    prop = db.session.scalar(select(Property).where(Property.code == form.get("property_code")))
    if prop is None:
        errors.append("Choose a property.")
    level = form.get("experience_level")
    if level not in LEVELS:
        errors.append("Choose an experience level.")
    try:
        years = int(form.get("experience_years") or 0)
        if not 0 <= years <= 60:
            raise ValueError
    except ValueError:
        errors.append("Years of experience must be a whole number between 0 and 60.")
        years = 0
    try:
        joining = date.fromisoformat(form.get("joining_date") or "")
    except ValueError:
        errors.append("Enter the joining date.")
        joining = None
    manager = (form.get("reporting_manager_code") or "").strip().upper() or None
    shift = form.get("shift_pattern") or "day"
    if shift not in SHIFTS:
        errors.append("Choose a shift pattern.")
    if errors:
        raise PeopleError(" ".join(errors))
    return {"name": name, "job_role_id": role.id, "property_id": prop.id,
            "department": (form.get("department") or "").strip() or role.department, "experience_level": level,
            "experience_years": years, "previous_experience": (form.get("previous_experience") or "").strip() or None,
            "joining_date": joining, "reporting_manager_code": manager, "shift_pattern": shift,
            "certifications": _aliases(form.get("certifications"))}


def create_employee(form, actor):
    code = (form.get("employee_code") or "").strip().upper()
    if not EMPLOYEE_CODE.match(code):
        raise PeopleError("The employee code must be a letter followed by 3-6 digits, e.g. E013.")
    if db.session.scalar(select(Employee).where(Employee.employee_code == code)):
        raise PeopleError("An employee with this code already exists.")
    fields = _employee_fields(form)
    employee = Employee(organization_id=_org_id(), employee_code=code, assignments=[], **fields)
    db.session.add(employee)
    audit.record("employee.created", "employee", code, actor=actor,
                 after={"name": fields["name"], "role": form.get("role_code")}, commit=False)
    db.session.commit()
    return employee


def update_employee(employee, form, actor):
    fields = _employee_fields(form)
    before = {k: getattr(employee, k) for k in ("name", "job_role_id", "experience_level", "joining_date")}
    for k, v in fields.items():
        setattr(employee, k, v)
    audit.record("employee.updated", "employee", employee.employee_code, actor=actor,
                 before={k: str(v) for k, v in before.items()},
                 after={k: str(fields[k]) for k in before}, commit=False)
    db.session.commit()
    return employee
