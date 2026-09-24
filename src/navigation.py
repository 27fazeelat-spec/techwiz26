"""The sidebar for each role: only the pages that role works in every day.

A page still needs its permission (src/rbac.py); this list decides what is offered, not what is allowed.
Each entry: (label, endpoint, icon, active-when prefix of the current endpoint or blueprint).
"""

NAV = {
    "admin": [
        ("Home", [("Overview", "main.admin_dashboard", "home", "main.admin_dashboard")]),
        ("Onboarding", [("Plans board", "main.trainer_dashboard", "grid", "main.trainer_dashboard"),
                        ("Employees", "plans.employees", "users", "plans."),
                        ("Review queue", "review.queue", "inbox", "review.")]),
        ("Knowledge", [("Documents", "documents.index", "file", "documents."),
                       ("Policy changes", "changes.index", "split", "changes."),
                       ("Security scan", "ground_truth.security", "shield", "ground_truth.security")]),
        ("Ground truth", [("Requirements", "ground_truth.requirements", "list", "ground_truth.requirement"),
                          ("Conflicts", "ground_truth.conflicts", "split", "ground_truth.conflict"),
                          ("Role matrix", "ground_truth.matrix_index", "grid", "ground_truth.matrix")]),
        ("Organisation", [("Job roles", "people.roles", "users", "people."),
                          ("Reports", "reports.index", "file", "reports.")]),
        ("Settings", [("Employee home", "settings.employee_home", "home", "settings.employee_home"),
                      ("Roles & access", "settings.pages", "lock", "settings.pages")]),
    ],
    "training_manager": [
        ("Home", [("Plans board", "main.trainer_dashboard", "home", "main.trainer_dashboard")]),
        ("Onboarding", [("Employees", "plans.employees", "users", "plans."),
                        ("Job roles", "people.roles", "grid", "people.")]),
        ("Knowledge", [("Documents", "documents.index", "file", "documents."),
                       ("Policy changes", "changes.index", "split", "changes."),
                       ("Requirements", "ground_truth.requirements", "list", "ground_truth.requirement"),
                       ("Role matrix", "ground_truth.matrix_index", "grid", "ground_truth.matrix")]),
        ("Results", [("Reports", "reports.index", "file", "reports.")]),
    ],
    "reviewer": [
        ("Home", [("My reviews", "main.reviewer_dashboard", "home", "main.reviewer_dashboard")]),
        ("Decide", [("Review queue", "review.queue", "inbox", "review."),
                    ("Conflicts", "ground_truth.conflicts", "split", "ground_truth.conflict")]),
        ("Look up", [("Plans", "plans.employees", "users", "plans."),
                     ("Requirements", "ground_truth.requirements", "list", "ground_truth.requirement")]),
        ("Results", [("Reports", "reports.index", "file", "reports.")]),
    ],
    "manager": [
        ("Home", [("My team", "main.team_dashboard", "users", "main.team_dashboard"),
                  ("Team reports", "reports.index", "file", "reports.")]),
    ],
    "employee": [
        ("", [("Home", "main.employee_dashboard", "home", "main.employee_dashboard"),
              ("My Learning", "learning.modules", "book", "learning.module"),
              ("My Progress", "learning.progress_page", "chart", "learning.progress_page"),
              ("Assessments", "learning.assessments", "check", "learning.assessments"),
              ("Resources", "learning.resources", "file", "learning.resources"),
              ("Calendar", "learning.calendar", "calendar", "learning.calendar"),
              ("Certificate", "learning.certificate", "trophy", "learning.certificate")]),
    ],
}


# Demo visitors see what the administrator sees (read-only), without Settings, plus a sample employee's home.
NAV["demo"] = [g for g in NAV["admin"] if g[0] != "Settings"] + [
    ("Try it", [("See as an employee", "tryout.employee", "user", "tryout.employee")])]


def items_for(role):
    """The sidebar for a role: its default pages, minus what the administrator hid, plus what they added
    (Settings > Roles & access). Added pages appear under the group they have in the administrator's sidebar."""
    from src.services import workspace
    shown = workspace.pages_for(role)
    if shown is None:
        return NAV.get(role, [])
    groups = [(g, [l for l in links if l[1] in shown]) for g, links in NAV.get(role, [])]
    present = {l[1] for _, links in groups for l in links}
    extra = {}
    for endpoint, label, icon, match, group in workspace.catalog():
        if endpoint in shown and endpoint not in present:
            extra.setdefault(group, []).append((label, endpoint, icon, match))
    for g, links in groups:
        if g in extra:
            links.extend(extra.pop(g))
    groups += list(extra.items())
    return [(g, links) for g, links in groups if links]


def is_active(match, endpoint, blueprint):
    if match.endswith("."):
        return (blueprint or "") + "." == match
    return (endpoint or "").startswith(match)
