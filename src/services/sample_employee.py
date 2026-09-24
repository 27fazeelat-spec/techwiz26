"""A made-up new hire at a made-up hotel, for demo visitors' "See it as an employee" view.

Nothing here comes from the database or from a client workspace: the hotel, the person, the modules and the tasks
are invented, so a demo visitor never sees a real company's data. Dates are relative to today.
"""
from datetime import timedelta
from types import SimpleNamespace as NS

BRAND = {"name": "Harbour View", "tagline": "Hotels · a sample workspace", "product_name": "SkillSprint demo",
         "logo": "image/logo.png", "logo_light": "image/logo.png"}

MODULES = [  # key, title, purpose, category, minutes, steps done, steps total, has quiz, quiz passed
    ("M01", "Welcome to Harbour View", "Who we are, how a shift runs and who to ask on your first day.", "Company Orientation", 30, 12, 12, True, True),
    ("M02", "Front desk essentials", "Check-in, check-out and room keys, done the same way by everyone.", "Front Office Operations", 60, 9, 14, True, False),
    ("M03", "Guest privacy basics", "What guest information you may keep, show or share, and for how long.", "Data Privacy", 40, 2, 10, True, False),
    ("M04", "Fire and life safety", "Alarms, assembly points and helping guests who need assistance.", "Fire & Life Safety", 45, 0, 11, True, False),
    ("M05", "When a guest is unhappy", "Listening, putting things right and knowing when to call the duty manager.", "Guest Service Recovery", 35, 0, 8, False, False),
    ("M06", "Payments and cash", "Deposits, card payments and closing your float at the end of a shift.", "Payment & Cash Handling", 45, 0, 12, True, False),
]


def context(today):
    joined = today - timedelta(days=4)
    modules = []
    for i, (key, title, purpose, category, minutes, done, total, quiz, passed) in enumerate(MODULES):
        due = None if done == total else joined + timedelta(days=[0, 0, 6, 13, 29, 29][i])
        modules.append({"module": NS(module_key=key, title=title, purpose=purpose, category=category, estimated_minutes=minutes),
                        "done": done, "total": total, "pct": round(100 * done / total), "due": due,
                        "has_quiz": quiz, "quiz_passed": passed, "quiz_failed": False})
    done = sum(m["done"] for m in modules)
    total = sum(m["total"] for m in modules)
    stages = [NS(code=c, label=l, done=d, total=t, due=joined + timedelta(days=o), state="done" if d == t else "open")
              for c, l, d, t, o in [("D1", "Day 1", 12, 12, 0), ("W1", "Week 1", 9, 16, 6), ("W2", "Week 2", 2, 14, 13),
                                    ("D30", "First 30 Days", 0, 18, 29), ("D60", "First 60 Days", 0, 7, 59), ("D90", "First 90 Days", 0, 2, 89)]]
    by_key = {m["module"].module_key: m["module"] for m in modules}

    def step(module, kind, text, days, key):
        return (NS(due_date=today + timedelta(days=days), status="not_started"),
                NS(item_type=kind, item_key=f"{module}.{key}", content={"activity": text, "description": text}), by_key[module])
    upcoming = [
        step("M02", "task", "Check in two guests with your buddy watching, then swap roles", 0, "T1"),
        step("M02", "checklist", "Collect your name badge and locker key from the duty manager", 1, "C3"),
        step("M03", "checklist", "Read how long guest ID copies may be kept, and where they are stored", 2, "C1"),
        step("M03", "quiz_question", "Guest privacy basics: five questions", 3, "Q"),
        step("M04", "scenario", "The fire alarm sounds during check-in: what do you do first?", 9, "S1"),
        step("M06", "task", "Close a practice float with your supervisor", 25, "T2"),
    ]
    return {
        "employee": NS(name="Alex Morgan", joining_date=joined, job_role=NS(name="Front Desk Associate")),
        "plan": True,
        "summary": {"modules": modules, "done": done, "total": total, "pct": round(100 * done / total),
                    "status": "On Track", "overdue": 0, "submitted": 0},
        "stages": [vars(s) for s in stages],
        "upcoming": upcoming,
    }
