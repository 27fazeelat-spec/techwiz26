"""Build comparison rows: one per requirement expected by the matrix or produced by Gemini.

The two pipelines are compared on structured attributes and source references, never on wording
(SRS "Important Dual-Pipeline Rule").
"""
from role_matrix.conditions import applies

FIELD_LABELS = {"included": "inclusion", "mandatory": "mandatory status", "priority": "priority",
                "due_stage": "due stage", "module_category": "module category", "source_document": "source document",
                "source_section": "source section", "task": "practical task", "assessment_topic": "assessment coverage"}


def _norm(value):
    return value.strip().lower() if isinstance(value, str) else value


def compare(ctx, requirement_statuses):
    outline = ctx.outline_reqs()
    modules = {m["module_key"]: m for m in ctx.modules}
    tasks, assessed = set(), set()
    for m in ctx.modules:
        for item in m["items"]:
            if item["item_type"] in ("task", "scenario"):
                tasks.update(item.get("requirement_ids", []))
            if item["item_type"] in ("quiz_question", "assessment"):
                assessed.update(item.get("requirement_ids", []))
        if any(i["item_type"] == "assessment" for i in m["items"]):
            assessed.update(m.get("requirement_ids", []))

    expected = {r: row for r, row in ctx.matrix.items() if applies(row.get("condition"), ctx.employee) is not False}
    rows = []
    for req_id in sorted(set(expected) | set(outline)):
        row, gen = expected.get(req_id), outline.get(req_id)
        known = ctx.requirements.get(req_id, {})
        module = modules.get(gen["module_key"]) if gen else None
        python = {
            "included": row is not None,
            "mandatory": row["mandatory"] if row else None,
            "priority": row["priority"] if row else None,
            "due_stage": row["due_stage"] if row else None,
            "module_category": row["competency"] if row else None,
            "source_document": known.get("doc_id"),
            "source_section": known.get("section_id"),
            "task": (row["assessment_requirement"] == "Practical") if row else None,
            "assessment_topic": (row["assessment_requirement"] not in ("None", "Checklist", "Acknowledgement")) if row else None,
        }
        genai = {
            "included": gen is not None,
            "mandatory": gen["mandatory"] if gen else None,
            "priority": gen["priority"] if gen else None,
            "due_stage": gen["due_stage"] if gen else None,
            "module_category": gen.get("category") if gen else None,
            "source_document": gen["source_document_id"] if gen else None,
            "source_section": gen["source_section_id"] if gen else None,
            "task": req_id in tasks if gen else None,
            "assessment_topic": req_id in assessed if gen else None,
        }
        fields = {}
        for name in python:
            if name != "included" and (row is None or gen is None):
                continue                                   # nothing to compare when one side is absent
            if name == "task" and not python["task"]:
                continue                                   # extra tasks are fine; only missing required ones count
            if name == "assessment_topic" and not python["assessment_topic"]:
                continue
            fields[name] = {"python": python[name], "genai": genai[name],
                            "match": _norm(python[name]) == _norm(genai[name])}
        mismatches = [n for n, f in fields.items() if not f["match"]]
        status = requirement_statuses.get(req_id, "Verified")
        rows.append({
            "req_id": req_id, "role_code": ctx.role_code,
            "source": f"{known.get('doc_id', '?')} §{known.get('section_id', '?')}",
            "fields": fields, "overall_match": not mismatches,
            "coverage_status": ("Covered" if gen else "Missing") if row and row["mandatory"] else
                               ("Included" if gen else "Not included"),
            "traceability_status": "Traced" if known else "Untraced",
            "validation_status": status,
            "explanation": _explain(req_id, row, gen, fields, mismatches, known),
        })
    return rows


def _explain(req_id, row, gen, fields, mismatches, known):
    source = f"{known.get('doc_id')} §{known.get('section_id')}" if known else "no source"
    if row is None and gen is not None:
        return (f"GenAI included {req_id}, but the matrix does not expect it for this employee "
                f"({'unknown requirement' if not known else 'another role or a condition that does not apply'}).")
    if gen is None:
        return (f"The matrix expects {req_id} ({'mandatory' if row['mandatory'] else 'optional'}, {source}); "
                "GenAI left it out.")
    if not mismatches:
        return "GenAI and the matrix agree on every compared field."
    parts = [f"{FIELD_LABELS[n]}: GenAI {fields[n]['genai']!r}, matrix {fields[n]['python']!r}" for n in mismatches]
    return "; ".join(parts) + f" ({source})."
