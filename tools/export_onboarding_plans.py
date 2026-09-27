"""Export onboarding plans to reports/onboarding_plans/ as Markdown (to read) and JSON (the full stored plan).

Usage:  python tools/export_onboarding_plans.py E001 E002 ...

For each employee code, the plan given to the employee is exported; if none has been given yet, the latest
plan that is not superseded or failed. Read-only: nothing in the database changes and no GenAI call is made.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from database import db  # noqa: E402
from database.models import Employee, Plan  # noqa: E402
from run import app  # noqa: E402

OUT = ROOT / "reports" / "onboarding_plans"
STAGES = {"D1": "Day 1", "W1": "Week 1", "W2": "Week 2", "D30": "30 days", "D60": "60 days", "D90": "90 days"}
TYPES = [("objective", "Learning objectives"), ("checklist", "Checklist"), ("task", "Tasks"),
         ("scenario", "Scenarios"), ("quiz_question", "Quiz"), ("assessment", "Assessment")]


def pick_plan(employee):
    plans = db.session.scalars(select(Plan).where(Plan.employee_id == employee.id)
                               .order_by(Plan.version.desc())).all()
    given = [p for p in plans if p.approved_at]
    if given:
        return given[0]
    usable = [p for p in plans if p.status not in ("superseded", "Failed")]
    return usable[0] if usable else None


def stage(code):
    return STAGES.get(code or "", code or "")


def pct(value):
    return "n/a" if value is None else f"{value:.0f}%"


def source(item):
    return f"{item.source_doc_id} §{item.source_section_id}" if item.source_doc_id else ""


def reqs(item):
    return ", ".join(item.content.get("requirement_ids") or []) or ""


def item_md(item):
    c = item.content
    cite = " · ".join(x for x in (reqs(item), source(item)) if x)
    cite = f" *({cite})*" if cite else ""
    if item.item_type == "objective":
        return [f"- {c.get('text', '')}{cite}"]
    if item.item_type == "checklist":
        return [f"- [ ] {c.get('activity', '')} — due {stage(item.stage)}{cite}"]
    if item.item_type == "task":
        out = [f"- **{c.get('description', '')}** — due {stage(item.stage)}, {item.difficulty or 'any level'}{cite}"]
        if c.get("expected_outcome"):
            out.append(f"  - Expected outcome: {c['expected_outcome']}")
        if c.get("completion_criteria"):
            out.append(f"  - Done when: {c['completion_criteria']}")
        return out
    if item.item_type == "scenario":
        out = [f"- **Situation:** {c.get('situation', '')}{cite}"]
        out += [f"  - {a}" for a in c.get("expected_actions") or []]
        return out
    if item.item_type == "quiz_question":
        out = [f"- **{c.get('question', '')}**{cite}"]
        right = set(c.get("correct_options") or [])
        for i, option in enumerate(c.get("options") or []):
            out.append(f"  - {'✔' if i in right else '○'} {option}")
        if c.get("explanation"):
            out.append(f"  - *Why:* {c['explanation']}")
        return out
    if item.item_type == "assessment":
        out = [f"- **{c.get('topic', '')}** ({c.get('type', '')}){cite}"]
        for r in c.get("rubric") or []:
            out.append(f"  - {r.get('criterion', '')} ({r.get('weight', 0)}%): {r.get('pass_condition', '')}")
        return out
    return [f"- {json.dumps(c, ensure_ascii=False)}"]


def plan_md(e, p):
    items = [i for m in p.modules for i in m.items]
    lines = [
        f"# Onboarding plan: {e.name} — {e.job_role.name}",
        "",
        "| | |",
        "|---|---|",
        f"| Employee | {e.employee_code} · {e.name} |",
        f"| Job role | {e.job_role.name} ({e.job_role.code}) |",
        f"| Property / department | {e.property.name} / {e.department} |",
        f"| Experience / shift | {e.experience_level} / {e.shift_pattern} |",
        f"| Joining date | {e.joining_date:%d %B %Y} |",
        f"| Plan | {p.plan_code} version {p.version} |",
        f"| Checked against | matrix version {p.matrix_version_id} |",
        f"| Generated | {p.created_at:%d %B %Y %H:%M} |",
        f"| Given to the employee | {p.approved_at:%d %B %Y %H:%M} |" if p.approved_at else
        "| Given to the employee | not yet |",
        f"| Validation status | {p.status} |",
        f"| Mandatory coverage | {pct(p.score_coverage)} |",
        f"| Source traceability | {pct(p.score_traceability)} (mandatory items {pct(p.score_traceability_mandatory)}) |",
        f"| Requirement consistency (GenAI vs matrix) | {pct(p.score_requirement_consistency)} |",
        f"| Findings | {p.count_missing or 0} missing, {p.count_unsupported or 0} unsupported, "
        f"{p.count_contradictions or 0} contradictions, {p.count_duplicates or 0} duplicates |",
        f"| Content | {len(p.modules)} modules, {len(items)} items |",
        "",
        "Every item cites its requirement IDs and source document section. Content was written by Gemini and checked by "
        "the Python validation pipeline; statuses and scores are computed by Python.",
        "",
    ]
    for m in sorted(p.modules, key=lambda m: m.position):
        lines += [f"## {m.module_key}. {m.title}", "",
                  f"*{m.category} · due {stage(m.stage)} · about {m.estimated_minutes or '?'} minutes*", ""]
        if m.purpose:
            lines += [m.purpose, ""]
        if m.key_concepts:
            lines += ["**Key concepts:** " + "; ".join(m.key_concepts), ""]
        for kind, heading in TYPES:
            group = [i for i in sorted(m.items, key=lambda i: i.position) if i.item_type == kind]
            if group:
                lines += [f"### {heading}", ""]
                for i in group:
                    lines += item_md(i)
                lines.append("")
        if m.completion_criteria:
            lines += [f"**Module complete when:** {m.completion_criteria}", ""]
    return "\n".join(lines)


def plan_json(e, p):
    return {
        "employee": {"code": e.employee_code, "name": e.name, "job_role": e.job_role.name,
                     "job_role_code": e.job_role.code, "property": e.property.name, "department": e.department,
                     "experience_level": e.experience_level, "shift_pattern": e.shift_pattern,
                     "joining_date": e.joining_date.isoformat()},
        "plan": {"code": p.plan_code, "version": p.version, "status": p.status,
                 "matrix_version_id": p.matrix_version_id, "created_at": p.created_at.isoformat(),
                 "given_at": p.approved_at.isoformat() if p.approved_at else None,
                 "scores": {"coverage": p.score_coverage, "traceability": p.score_traceability,
                            "traceability_mandatory": p.score_traceability_mandatory,
                            "requirement_consistency": p.score_requirement_consistency},
                 "findings": {"missing": p.count_missing, "unsupported": p.count_unsupported,
                              "contradictions": p.count_contradictions, "duplicates": p.count_duplicates}},
        "modules": [{
            "key": m.module_key, "title": m.title, "category": m.category, "stage": m.stage,
            "purpose": m.purpose, "estimated_minutes": m.estimated_minutes, "key_concepts": m.key_concepts,
            "assessment_topics": m.assessment_topics, "completion_criteria": m.completion_criteria,
            "items": [{"key": i.item_key, "type": i.item_type, "stage": i.stage, "difficulty": i.difficulty,
                       "source_document_id": i.source_doc_id, "source_section_id": i.source_section_id,
                       "validation_status": i.status, "content": i.content}
                      for i in sorted(m.items, key=lambda i: i.position)],
        } for m in sorted(p.modules, key=lambda m: m.position)],
    }


def main(codes):
    if not codes:
        sys.exit(__doc__)
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    with app.app_context():
        for code in codes:
            e = db.session.scalar(select(Employee).where(Employee.employee_code == code))
            p = pick_plan(e) if e else None
            if not p or not p.modules:
                print(f"{code}: no plan to export")
                continue
            name = f"{e.employee_code}_{e.job_role.name.replace('&', 'and').replace(' ', '_')}"
            (OUT / f"{name}.md").write_text(plan_md(e, p) + "\n", encoding="utf-8")
            (OUT / f"{name}.json").write_text(json.dumps(plan_json(e, p), ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8")
            items = sum(len(m.items) for m in p.modules)
            index.append((e, p, name, items))
            print(f"{code}: {p.plan_code} v{p.version} -> {name}.md / .json")
    rows = ["# Onboarding plans", "",
            f"{len(index)} onboarding plans exported from SkillSprint with `python tools/export_onboarding_plans.py`. "
            "Each plan is given as Markdown (to read) and JSON (the full stored plan with citations and validation "
            "status per item). No plan was edited for this export.", "",
            "| Employee | Job role | Plan | Status | Coverage | Traceability | Modules / items | Given | Files |",
            "|---|---|---|---|---|---|---|---|---|"]
    for e, p, name, items in index:
        rows.append(f"| {e.employee_code} {e.name} | {e.job_role.name} | {p.plan_code} v{p.version} | {p.status} | "
                    f"{pct(p.score_coverage)} | {pct(p.score_traceability)} | {len(p.modules)} / {items} | "
                    f"{p.approved_at:%d %b %Y}" if p.approved_at else "")
        if not p.approved_at:
            rows[-1] = (f"| {e.employee_code} {e.name} | {e.job_role.name} | {p.plan_code} v{p.version} | {p.status} | "
                        f"{pct(p.score_coverage)} | {pct(p.score_traceability)} | {len(p.modules)} / {items} | not yet")
        rows[-1] += f" | [{name}.md]({name}.md) · [json]({name}.json) |"
    (OUT / "README.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
