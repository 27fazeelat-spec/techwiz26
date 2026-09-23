"""Which job roles a requirement applies to.

Order of evidence:
  1. roles named in the clause's subject ("Guest Relations Executives and Front Office Associates may ...")
  2. roles named in the section headings (role-description documents: "1. Front Office Associate")
  3. the document's audience ("Applies To"), via role names, aliases and department names
  4. otherwise everyone

Roles are resolved at matrix-build time from the current job roles, so a role added later
(e.g. a new "Night Auditor" with alias "auditor") picks up existing requirements without re-extraction.
"""
import re

EVERYONE = re.compile(r"\b(all (employees|colleagues|staff)|every (new )?employee|all properties)\b", re.I)


def _mentions(text, roles):
    """Role codes whose name or alias appears in text (longest aliases matched first)."""
    found, remaining = [], f" {text.lower()} "
    terms = sorted(((alias.lower(), role.code) for role in roles for alias in [role.name, *(role.aliases or [])]),
                   key=lambda t: len(t[0]), reverse=True)
    for term, code in terms:
        pattern = rf"(?<![a-z]){re.escape(term)}(?![a-z])"
        if re.search(pattern, remaining):
            if code not in found:
                found.append(code)
            remaining = re.sub(pattern, " ", remaining)
    return found


def _departments(text, roles, short_names=False):
    """Role codes whose department is named in text ("Finance must ...", "Front Office, Sales and ...").

    With short_names, a department's first word also counts ("Revenue" for Revenue Management), but only
    when capitalised, so ordinary words ("guest data", "food") do not trigger it.
    """
    codes = []
    for role in roles:
        dept = role.department or ""
        found = re.search(rf"\b{re.escape(dept)}\b", text, re.I) if dept else None
        if not found and short_names and dept:
            first = dept.split()[0]
            found = len(first) > 3 and re.search(rf"\b{re.escape(first)}\b", text)
        if found and role.code not in codes:
            codes.append(role.code)
    return codes


def audience(applies_to_text, roles):
    text = applies_to_text or ""
    if not text or EVERYONE.search(text):
        return ["ALL"]
    codes = _mentions(text, roles)
    codes += [c for c in _departments(text, roles, short_names=True) if c not in codes]
    return codes or ["ALL"]


def resolve_roles(subject, heading_path, applies_to_text, roles):
    codes = _mentions(subject or "", roles) or _departments(subject or "", roles)
    if codes:
        return codes
    if subject and EVERYONE.search(subject):
        return audience(applies_to_text, roles)
    codes = _mentions(" ".join(heading_path or []), roles)
    if codes:
        return codes
    return audience(applies_to_text, roles)
