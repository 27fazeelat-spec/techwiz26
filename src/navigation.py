"""The sidebar for each role: only the pages that role works in every day.

A page still needs its permission (src/rbac.py); this list decides what is offered, not what is allowed.
Each entry: (label, endpoint, icon, active-when prefix of the current endpoint or blueprint).
"""

NAV = {
    "admin": [
        ("Home", [("Home", "main.admin_dashboard", "home", "main.admin_dashboard")]),
        ("Onboarding", [("Plans board", "main.trainer_dashboard", "grid", "main.trainer_dashboard"),
                        ("Employees", "plans.employees", "users", "plans."),
                        ("Approvals", "review.queue", "inbox", "review.")]),
        ("Knowledge", [("All documents", "documents.index", "file", "documents."),
                       ("What changed", "changes.index", "split", "changes."),
                       ("Safety check", "ground_truth.security", "shield", "ground_truth.security")]),
        ("Ground truth", [("All rules", "ground_truth.requirements", "list", "ground_truth.requirement"),
                          ("Clashing policies", "ground_truth.conflicts", "split", "ground_truth.conflict"),
                          ("Who learns what", "ground_truth.matrix_index", "grid", "ground_truth.matrix"),
                          ("Is it covered?", "ground_truth.topic_check", "search", "ground_truth.topic_check")]),
        ("Organisation", [("Job roles", "people.roles", "users", "people."),
                          ("Reports", "reports.index", "file", "reports.")]),
        ("Settings", [("Employee home", "settings.employee_home", "home", "settings.employee_home"),
                      ("Roles & access", "settings.pages", "lock", "settings.pages"),
                      ("Users", "settings.users", "users", "settings.users")]),
    ],
    "training_manager": [
        ("Home", [("Plans board", "main.trainer_dashboard", "home", "main.trainer_dashboard")]),
        ("Onboarding", [("Employees", "plans.employees", "users", "plans."),
                        ("Job roles", "people.roles", "grid", "people.")]),
        ("Knowledge", [("All documents", "documents.index", "file", "documents."),
                       ("What changed", "changes.index", "split", "changes."),
                       ("All rules", "ground_truth.requirements", "list", "ground_truth.requirement"),
                       ("Who learns what", "ground_truth.matrix_index", "grid", "ground_truth.matrix"),
                       ("Is it covered?", "ground_truth.topic_check", "search", "ground_truth.topic_check")]),
        ("Results", [("Reports", "reports.index", "file", "reports.")]),
    ],
    "reviewer": [
        ("Home", [("My reviews", "main.reviewer_dashboard", "home", "main.reviewer_dashboard")]),
        ("Decide", [("Approvals", "review.queue", "inbox", "review."),
                    ("Clashing policies", "ground_truth.conflicts", "split", "ground_truth.conflict")]),
        ("Look up", [("Plans", "plans.employees", "users", "plans."),
                     ("All rules", "ground_truth.requirements", "list", "ground_truth.requirement"),
                     ("Is it covered?", "ground_truth.topic_check", "search", "ground_truth.topic_check")]),
        ("Results", [("Reports", "reports.index", "file", "reports.")]),
    ],
    "manager": [
        ("Home", [("My team", "main.team_dashboard", "users", "main.team_dashboard"),
                  ("Team questions", "bot.team_questions", "chat", "bot.team_questions"),
                  ("Team reports", "reports.index", "file", "reports.")]),
    ],
    "employee": [
        ("", [("Home", "main.employee_dashboard", "home", "main.employee_dashboard"),
              ("Modules", "learning.modules", "book", "learning.module"),
              ("Progress", "learning.progress_page", "chart", "learning.progress_page"),
              ("Quizzes", "learning.assessments", "check", "learning.assessments"),
              ("Resources", "learning.resources", "file", "learning.resources"),
              ("Ask a question", "bot.ask", "chat", "bot.ask"),
              ("Calendar", "learning.calendar", "calendar", "learning.calendar"),
              ("Certificate", "learning.certificate", "trophy", "learning.certificate")]),
    ],
}


# Demo visitors see what the administrator sees (read-only), without Settings, plus a sample employee's home.
NAV["demo"] = [g for g in NAV["admin"] if g[0] != "Settings"] + [
    ("Try it", [("See as an employee", "tryout.employee", "user", "tryout.employee"),
                ("Ask a question", "bot.ask", "chat", "bot.ask")])]


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


# The sidebar shows one entry per hub; the hub's pages appear as tabs at the top of each of them.
# A role's home page and pages outside every hub keep their own sidebar entry.
HUBS = [
    ("documents", "Documents", "file", ("documents.index", "changes.index", "ground_truth.security")),
    ("rules", "Rules", "list", ("ground_truth.requirements", "ground_truth.conflicts", "ground_truth.matrix_index",
                               "ground_truth.topic_check")),
    ("people", "Employees", "users", ("plans.employees", "main.trainer_dashboard", "people.roles")),
    ("approvals", "Approvals", "inbox", ("review.queue",)),
    ("more", "Reports & settings", "chart", ("reports.index", "settings.employee_home", "settings.pages", "settings.users")),
    ("learn", "My learning", "book", ("learning.modules", "learning.assessments", "learning.resources")),
    ("mine", "My progress", "chart", ("learning.progress_page", "learning.calendar", "learning.certificate")),
]
HUB_OF = {endpoint: hub for hub in HUBS for endpoint in hub[3]}


def sidebar_for(role, endpoint, blueprint):
    """Sidebar entries for a role, pages grouped into hubs: [{label, endpoint, icon, hub, active, tabs}].
    tabs lists the hub's pages [(label, endpoint, active)] when it has more than one."""
    links = [link for _, group in items_for(role) for link in group]
    entries, by_hub = [], {}
    for i, (label, page, icon, match) in enumerate(links):
        hub = HUB_OF.get(page) if i else None                  # the first link is the role's home
        if hub is None:
            entries.append({"label": label, "endpoint": page, "icon": icon, "hub": "", "pages": [(label, page, match)]})
        elif hub[0] in by_hub:
            by_hub[hub[0]]["pages"].append((label, page, match))
        else:
            by_hub[hub[0]] = {"label": hub[1], "endpoint": page, "icon": hub[2], "hub": hub[0], "pages": [(label, page, match)]}
            entries.append(by_hub[hub[0]])
    for e in entries:
        if e["hub"]:                                           # tabs, and the page the entry opens, follow HUBS order
            order = HUB_OF[e["endpoint"]][3]
            e["pages"].sort(key=lambda p: order.index(p[1]))
            e["endpoint"] = e["pages"][0][1]
        states =[(label, page, is_active(match, endpoint, blueprint)) for label, page, match in e.pop("pages")]
        e["active"] = any(on for _, _, on in states)
        if len(states) == 1:
            e["label"] = states[0][0]                          # a hub with one page is named after that page
        e["tabs"] = states if len(states) > 1 else []
    return entries


def is_active(match, endpoint, blueprint):
    if match.endswith("."):
        return (blueprint or "") + "." == match
    return (endpoint or "").startswith(match)
