"""Workspace settings the administrator composes in the browser (Organization.settings):

* the employee home: which sections show and in what order, the carousel slides and their photos, and the
  company's own words (welcome line, closing quote);
* which pages each role sees in its sidebar.

Guardrails are in code, not in the settings: logo and colours are not editable here, a role only ever sees pages
its permissions allow (config/permissions.yaml), every role keeps its home page, employees always keep their
modules, and the certificate and progress rules are untouched. Every save is audited.
"""
import copy
import time
from pathlib import Path

from flask import current_app
from sqlalchemy import select

from database import audit, db
from database.models import Organization
from src.navigation import NAV

PHOTO_DIR = Path(__file__).resolve().parents[2] / "static" / "img" / "aurelle" / "photos"

# ---------------------------------------------------------------------------- employee home
SECTIONS = {                      # key: (label, what it shows, can be switched off)
    "hero": ("Highlights carousel", "Welcome, the next step, a quiz and the certificate, one at a time", True),
    "glance": ("Figures", "Plan complete, modules, quizzes, overdue and status", True),
    "journey": ("First ninety days", "The stages from Day 1 to 90 days", True),
    "modules": ("Modules", "The employee's modules; always shown so there is a way into the learning", False),
    "upcoming": ("Coming up", "Next due steps, quizzes ready to take and the certificate card", True),
    "quote": ("Closing line", "A photograph with the company's quote", True),
}
SLIDES = {"welcome": "Welcome", "next": "Up next", "quiz": "Quiz", "certificate": "Certificate"}
DEFAULT_HOME = {
    "sections": [{"key": k, "on": True} for k in SECTIONS],
    "slides": {"welcome": {"on": True, "photo": "hero"}, "next": {"on": True, "photo": "lobby"},
               "quiz": {"on": True, "photo": "pool"}, "certificate": {"on": True, "photo": "room"}},
    "welcome_line": "Every lesson here comes straight from our approved policies, so what you learn is what we do.",
    "quote": "Excellence is not a skill, it’s an attitude.",
    "quote_by": "",                                              # empty: the workspace name and tagline
    "quote_photo": "resort",
}
MAX_TEXT = {"welcome_line": 200, "quote": 140, "quote_by": 60}
PHOTO_CAPTIONS = {                # alt text and a short caption for each photo in static/img/aurelle/photos
    "amenities": ("Guest amenities laid out on a shelf", "Small things, done well"),
    "corridor": ("A long, bright hotel lounge", "The lounge before lunch"),
    "hero": ("A resort pool at night, lit from the rooms above", "Evening by the pool"),
    "interior": ("A calm living room with a curved sofa", "A residence, ready for its guests"),
    "kitchen": ("A chef at work in a hotel kitchen", "The kitchen at service time"),
    "lobby": ("A hotel lobby with tall windows", "The lobby at nine in the morning"),
    "pool-day": ("A pool with white umbrellas on a sunny day", "The pool, mid-morning"),
    "pool": ("Poolside loungers under orange umbrellas", "Poolside, before the guests arrive"),
    "reception": ("A reception bell on a front desk", "The front desk"),
    "resort": ("A resort courtyard with a long pool and palms", "The courtyard"),
    "room": ("A guest room made up with fresh linen", "A room, made ready for its guest"),
    "team": ("Colleagues' hands together over a table", "One team"),
    "training": ("A team in a bright meeting room", "Learning together"),
}


def caption(photo):
    return PHOTO_CAPTIONS.get(photo, ("", photo.replace("-", " ").capitalize()))

# ---------------------------------------------------------------------------- pages per role
ROLES = ("training_manager", "reviewer", "manager", "employee")
LOCKED = {                        # each role's home, which can never be hidden
    "training_manager": {"main.trainer_dashboard"},
    "reviewer": {"main.reviewer_dashboard"},
    "manager": {"main.team_dashboard"},
    "employee": {"main.employee_dashboard", "learning.modules"},
}
PAGE_PERMISSION = {               # the permission each page needs (mirrors the route decorators)
    "main.admin_dashboard": "dashboard.admin", "main.trainer_dashboard": "plans.view", "plans.employees": "plans.view",
    "review.queue": "review.view", "documents.index": "documents.view", "changes.index": "documents.view",
    "ground_truth.security": "security.view", "ground_truth.requirements": "requirements.view",
    "ground_truth.conflicts": "conflicts.view", "ground_truth.matrix_index": "matrix.view", "people.roles": "roles.view",
    "reports.index": "reports.view", "main.reviewer_dashboard": "review.view", "main.team_dashboard": "dashboard.team",
    "main.employee_dashboard": "dashboard.employee", "learning.modules": "learning.view",
    "learning.progress_page": "learning.view", "learning.assessments": "learning.view", "learning.resources": "learning.view",
    "learning.calendar": "learning.view", "learning.certificate": "learning.view",
}
REPORT_PERMISSIONS = ("reports.view", "reports.team")


def photos():
    return sorted(p.stem for p in PHOTO_DIR.glob("*.jpg"))


def catalog():
    """Every page a sidebar can offer, once: [(endpoint, label, icon, match, group)]. Built from the sidebars in
    src/navigation.py so a new page added there appears here automatically."""
    seen, out = set(), []
    for role in ("admin", "reviewer", "manager", "employee", "training_manager"):
        for group, links in NAV.get(role, []):
            for label, endpoint, icon, match in links:
                if endpoint not in seen:
                    seen.add(endpoint)
                    out.append((endpoint, label, icon, match, group or "Learning"))
    return out


def _role_can(role, endpoint):
    from src.rbac import role_has_permission
    need = PAGE_PERMISSION.get(endpoint)
    if endpoint == "reports.index":
        return any(role_has_permission(role, p) for p in REPORT_PERMISSIONS)
    return need is not None and role_has_permission(role, need)


def default_pages(role):
    return [endpoint for _, links in NAV.get(role, []) for _, endpoint, _, _ in links]


# ---------------------------------------------------------------------------- reading (short cache per worker)
_CACHE = {"at": 0.0, "value": None}
TTL = 20                          # seconds; several workers each refresh on their own within this time


def _raw():
    now = time.monotonic()
    if _CACHE["value"] is None or now - _CACHE["at"] > TTL or current_app.config.get("TESTING"):
        settings = db.session.scalar(select(Organization.settings).limit(1)) or {}
        _CACHE.update(at=now, value=copy.deepcopy(settings))
    return _CACHE["value"]


def employee_home():
    saved = _raw().get("employee_home") or {}
    home = copy.deepcopy(DEFAULT_HOME)
    home.update({k: v for k, v in saved.items() if k in home})
    known = [s for s in home["sections"] if s.get("key") in SECTIONS]
    known += [{"key": k, "on": True} for k in SECTIONS if k not in {s["key"] for s in known}]
    for s in known:
        if not SECTIONS[s["key"]][2]:
            s["on"] = True
    home["sections"] = known
    home["slides"] = {k: {**DEFAULT_HOME["slides"][k], **(home["slides"].get(k) or {})} for k in SLIDES}
    return home


def _choice(role):
    saved = (_raw().get("pages") or {}).get(role) or {}
    return set(saved.get("add") or []), set(saved.get("hide") or [])


def pages_for(role):
    """Endpoints this role's sidebar shows: its default pages, minus what the administrator hid, plus what they
    added; always within the role's permissions and always including its home."""
    if role == "admin" or role not in ROLES:
        return None                                              # None: the full default sidebar
    add, hide = _choice(role)
    order = [e for e, *_ in catalog()]
    shown = [e for e in default_pages(role) if e not in hide] + [e for e in order if e in add]
    return [e for e in dict.fromkeys(list(LOCKED[role]) + shown) if _role_can(role, e)]


def hidden_matches(role):
    """Match prefixes of pages the administrator removed from this role. Only those are blocked by URL too;
    pages that were never in the role's sidebar keep working as links from other pages."""
    if role == "admin" or role not in ROLES:
        return []
    _, hide = _choice(role)
    return [match for endpoint, _, _, match, _ in catalog() if endpoint in hide and endpoint not in LOCKED[role]]


# ---------------------------------------------------------------------------- saving
class SettingsError(ValueError):
    pass


def _org():
    org = db.session.scalar(select(Organization).limit(1))
    if org is None:
        raise SettingsError("No organisation is set up yet.")
    return org


def _save(key, value, actor, before):
    org = _org()
    settings = copy.deepcopy(org.settings or {})
    settings[key] = value
    org.settings = settings
    audit.record(f"settings.{key}", "organization", org.org_code, actor=actor, before=before, after=value, commit=False)
    db.session.commit()
    _CACHE["value"] = None


def save_employee_home(form, actor):
    order = [k for k in (form.get("order") or "").split(",") if k in SECTIONS]
    order += [k for k in SECTIONS if k not in order]
    sections = [{"key": k, "on": (not SECTIONS[k][2]) or form.get(f"section_{k}") == "on"} for k in order]
    available = set(photos())
    slides = {}
    for k in SLIDES:
        photo = form.get(f"slide_{k}_photo") or DEFAULT_HOME["slides"][k]["photo"]
        if photo not in available:
            raise SettingsError("Choose one of the listed photos.")
        slides[k] = {"on": form.get(f"slide_{k}") == "on", "photo": photo}
    if not any(s["on"] for s in slides.values()) and any(s["key"] == "hero" and s["on"] for s in sections):
        raise SettingsError("Keep at least one slide, or switch the carousel off.")
    quote_photo = form.get("quote_photo") or DEFAULT_HOME["quote_photo"]
    if quote_photo not in available:
        raise SettingsError("Choose one of the listed photos.")
    texts = {}
    for k, limit in MAX_TEXT.items():
        value = " ".join((form.get(k) or "").split())
        if len(value) > limit:
            raise SettingsError(f"Keep the {k.replace('_', ' ')} under {limit} characters.")
        texts[k] = value
    if not texts["welcome_line"]:
        texts["welcome_line"] = DEFAULT_HOME["welcome_line"]
    if not texts["quote"]:
        texts["quote"] = DEFAULT_HOME["quote"]
    home = {"sections": sections, "slides": slides, "quote_photo": quote_photo, **texts}
    _save("employee_home", home, actor, before=_raw().get("employee_home"))
    return home


def reset_employee_home(actor):
    _save("employee_home", copy.deepcopy(DEFAULT_HOME), actor, before=_raw().get("employee_home"))


def save_pages(form, actor):
    """Store each role's choice relative to its default sidebar: pages added and pages hidden."""
    pages = {}
    for role in ROLES:
        checked = {e for e, *_ in catalog() if form.get(f"{role}:{e}") == "on" and _role_can(role, e)} | LOCKED[role]
        default = set(default_pages(role))
        pages[role] = {"add": sorted(checked - default), "hide": sorted(default - checked)}
    _save("pages", pages, actor, before=_raw().get("pages"))
    return pages


def reset_pages(actor):
    _save("pages", {}, actor, before=_raw().get("pages"))
