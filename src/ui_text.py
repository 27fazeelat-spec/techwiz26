"""Plain-English wording for statuses and terms, in one place so every page says the same thing.

The stored values (e.g. "Requirement Missing") never change; only what people read does.
"""

ITEM_STATUS = {
    "Verified": ("Verified", "Every check passed: the item matches its source and the approved matrix."),
    "Verified with Warning": ("Verified, with notes", "Correct, but a minor check raised a note worth a look (for example a different due stage)."),
    "Partially Verified": ("Partly verified", "Some of the item is backed by the source and some is not."),
    "Source Support Missing": ("Not backed by the source", "The item states something the cited policy section does not say, or cites no valid section."),
    "Requirement Missing": ("Missing from the plan", "The approved matrix says this person must learn this rule, but the generated plan does not include it."),
    "Unsupported Requirement": ("Not required for this role", "The plan includes a rule that the approved matrix does not assign to this person's role or situation."),
    "Outdated Source": ("Expired source document", "The rule comes from a document that has passed its review date and has no replacement yet."),
    "Contradiction Detected": ("Conflicts with a stronger rule", "A higher-authority policy says something different, so this version must not be taught."),
    "Manual Review Required": ("Needs a person", "Python could not decide on its own; a reviewer has to look at it."),
}

PLAN_STATUS = {
    "Verified": ("Verified", "Every mandatory requirement is covered, cited and consistent with the approved sources."),
    "Verified with Warning": ("Verified, with notes", "All mandatory requirements are covered; minor notes are worth a look before assigning."),
    "Incomplete": ("Incomplete", "Some mandatory requirements from the approved matrix are missing from the plan."),
    "Unsupported": ("Unsupported content", "Some items are not backed by their source, or do not apply to this role."),
    "Contradictory": ("Contradicts policy", "Some items follow a rule that a stronger policy overrides."),
    "Manual Review Required": ("Needs a person", "Some items need a reviewer's decision."),
    "Failed": ("Generation failed", "The AI service did not return a plan, so nothing was validated or assigned."),
    "generating": ("Generating", "The plan is being written and checked."),
    "superseded": ("Replaced", "A newer version of this plan exists."),
}

DOC_STATUS = {
    "active": ("Active", "In force: used as a source for plans."),
    "superseded": ("Replaced", "A newer version replaced it; kept for history only."),
    "scheduled": ("Not yet in force", "Approved, but its effective date is in the future."),
    "expired": ("Expired", "Past its review date with no replacement; content from it is flagged."),
    "draft": ("Draft", "Not approved; never used as a source."),
    "pending": ("Processing", "Being processed."),
}

GLOSSARY = {
    "requirement": "A single rule taken from a policy, such as \"Delete passport scans within 7 days\". Found by Python from words like must and shall.",
    "matrix": "The list of which rules each job role must learn, by when. A person approves it, and every plan is checked against it.",
    "conflict": "Two policies that say different things about the same topic. The stronger document wins; if both have the same authority, a reviewer decides.",
    "coverage": "Of the mandatory rules this person must learn, how many the plan actually teaches.",
    "traceability": "How many plan items point to a real, current policy section that supports them.",
    "consistency": "How closely the AI's choices match the approved matrix, field by field (mandatory, stage, source, and so on).",
    "review": "Items Python could not verify, waiting for a person to approve, fix, override or regenerate them.",
    "precedence": "The order of authority between document types, for example a policy outranks an FAQ.",
    "quarantine": "A document section that looked like an instruction to the AI. It is kept as evidence but never used.",
    "stage": "When something must be done: Day 1, Week 1, Week 2, or within 30, 60 or 90 days.",
    "plan": "The onboarding written for one employee: modules with checklists, tasks, quizzes and an assessment.",
}


CATEGORY_ICONS = [("fire", "flame"), ("life safety", "flame"), ("privacy", "lock"), ("data", "lock"), ("security", "lock"),
                  ("guest", "bell"), ("service", "bell"), ("finance", "coin"), ("revenue", "chart"), ("sales", "hand"),
                  ("housekeeping", "bed"), ("food", "cup"), ("f&b", "cup"), ("beverage", "cup"), ("maintenance", "wrench"),
                  ("engineering", "wrench"), ("health", "heart"), ("safety", "heart"), ("hr", "users"), ("people", "users"),
                  ("orientation", "building"), ("company", "building"), ("conduct", "shield"), ("compliance", "shield")]


def category_icon(category):
    text = (category or "").lower()
    return next((icon for word, icon in CATEGORY_ICONS if word in text), "map")


CATEGORY_PHOTOS = [("fire", "pool"), ("life safety", "pool"), ("health", "pool"), ("safety", "pool"),
                   ("privacy", "corridor"), ("data", "corridor"), ("security", "corridor"), ("it ", "corridor"),
                   ("guest", "reception"), ("front office", "reception"), ("service", "reception"),
                   ("housekeeping", "room"), ("room", "room"), ("food", "kitchen"), ("f&b", "kitchen"), ("kitchen", "kitchen"),
                   ("maintenance", "interior"), ("engineering", "interior"), ("hr", "team"), ("people", "team"),
                   ("conduct", "training"), ("compliance", "training"), ("orientation", "lobby"), ("company", "lobby"),
                   ("finance", "interior"), ("revenue", "interior"), ("sales", "resort")]


def category_photo(category):
    text = f" {(category or '').lower()} "
    return "img/aurelle/photos/" + next((photo for word, photo in CATEGORY_PHOTOS if word in text), "resort") + ".jpg"


def label(kind, value):
    table = {"item": ITEM_STATUS, "plan": PLAN_STATUS, "doc": DOC_STATUS}[kind]
    return table.get(value, (value, ""))


def register(app):
    from src.navigation import is_active, items_for
    app.jinja_env.globals.update(status_label=label, glossary=GLOSSARY, nav_items=items_for, nav_active=is_active,
                                 category_icon=category_icon, category_photo=category_photo)
