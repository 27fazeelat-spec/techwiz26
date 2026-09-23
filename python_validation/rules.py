"""Validation rules. Each takes (ctx, settings) and returns findings. See documentation/02_Architecture.md 7.1."""
from difflib import SequenceMatcher

from python_validation.engine import F, rule
from python_validation.facts import facts, overlap, unsupported
from role_matrix.conditions import applies

FACT_ITEMS = ("checklist", "task", "scenario", "quiz_question")


def _expected(ctx):
    """Matrix rows that apply to this employee: (req_id -> row), plus rows whose condition cannot be decided."""
    expected, undecided = {}, {}
    for req_id, row in ctx.matrix.items():
        verdict = applies(row.get("condition"), ctx.employee)
        if verdict is True:
            expected[req_id] = row
        elif verdict is None:
            undecided[req_id] = row
    return expected, undecided


@rule("V-SCHEMA")
def schema(ctx, _):
    return [F("V-SCHEMA", "error", "Manual Review Required",
              f"Module {m['module_key']} has no valid generated content (Gemini output failed schema validation).",
              evidence={"module": m["module_key"]}) for m in ctx.modules if not m.get("content_ok", True)]


@rule("V-MATRIX")
def matrix_status(ctx, _):
    if ctx.matrix_approved:
        return []
    return [F("V-MATRIX", "warning", "Manual Review Required",
              "Validated against a draft Role Requirement Matrix. Approve the matrix before this plan can be verified.")]


@rule("V-REQ-ID")
def requirement_ids(ctx, _):
    out = []
    for req_id in ctx.outline_reqs():
        if req_id not in ctx.requirements:
            out.append(F("V-REQ-ID", "error", "Unsupported Requirement",
                         f"{req_id} does not exist in any current source document (possible hallucinated ID).",
                         req_id=req_id))
    for _, item in ctx.items():
        for req_id in item.get("requirement_ids", []):
            if req_id not in ctx.requirements:
                out.append(F("V-REQ-ID", "error", "Unsupported Requirement",
                             f"Item cites unknown requirement {req_id}.", item_key=item["item_key"], req_id=req_id))
    return out


@rule("V-SOURCE")
def sources(ctx, _):
    out = []
    for req_id, r in ctx.outline_reqs().items():
        known = ctx.requirements.get(req_id)
        if known and (r["source_document_id"], r["source_section_id"]) != (known["doc_id"], known["section_id"]):
            out.append(F("V-SOURCE", "warning", "Verified with Warning",
                         f"{req_id} is cited as {r['source_document_id']} §{r['source_section_id']}, but the clause is in "
                         f"{known['doc_id']} §{known['section_id']}.", req_id=req_id))
    for _, item in ctx.items(*FACT_ITEMS):
        key = (item.get("source_doc_id"), item.get("source_section_id"))
        if key not in ctx.sections:
            out.append(F("V-SOURCE", "error", "Source Support Missing",
                         f"Cited source {key[0]} §{key[1]} does not exist in any current document.",
                         item_key=item["item_key"], evidence={"cited": list(key)}))
    return out


@rule("V-OUTDATED")
def outdated(ctx, _):
    out = []
    for req_id in ctx.outline_reqs():
        known = ctx.requirements.get(req_id)
        if known and known["doc_status"] == "expired":
            out.append(F("V-OUTDATED", "warning", "Outdated Source",
                         f"{req_id} comes from {known['doc_id']}, which has expired with no replacement.", req_id=req_id))
    return out


@rule("V-COVERAGE")
def coverage(ctx, _):
    expected, undecided = _expected(ctx)
    outline, links = ctx.outline_reqs(), ctx.linked_requirements()
    out = []
    for req_id, row in expected.items():
        if not row["mandatory"]:
            continue
        if req_id not in outline:
            out.append(F("V-COVERAGE", "error", "Requirement Missing",
                         f"Mandatory requirement {req_id} is not in the plan.", req_id=req_id,
                         evidence={"source": f"{row['source_doc_id']} §{row['source_section_id']}", "text": row["text"]}))
        elif req_id not in links:
            out.append(F("V-COVERAGE", "error", "Requirement Missing",
                         f"Mandatory requirement {req_id} is listed in the outline but no module content covers it.",
                         req_id=req_id))
    for req_id, row in undecided.items():
        out.append(F("V-CONDITION", "warning", "Manual Review Required",
                     f"{req_id} applies only when {row['condition']['text']!r}; the employee profile does not say.",
                     req_id=req_id))
    return out


@rule("V-MANDATORY")
def mandatory(ctx, _):
    out = []
    for req_id, r in ctx.outline_reqs().items():
        row = ctx.matrix.get(req_id)
        if row and bool(r["mandatory"]) != bool(row["mandatory"]):
            out.append(F("V-MANDATORY", "warning", "Partially Verified",
                         f"GenAI marked {req_id} as {'mandatory' if r['mandatory'] else 'optional'}; the matrix says "
                         f"{'mandatory' if row['mandatory'] else 'optional'}.", req_id=req_id))
    return out


@rule("V-ROLE")
def role_relevance(ctx, _):
    out = []
    for req_id in ctx.outline_reqs():
        if req_id in ctx.requirements and req_id not in ctx.matrix:
            out.append(F("V-ROLE", "error", "Unsupported Requirement",
                         f"{req_id} is valid company content but does not apply to the {ctx.role_code} role.",
                         req_id=req_id, evidence={"text": ctx.requirements[req_id]["text"]}))
    return out


@rule("V-CONDITION")
def conditions(ctx, _):
    out = []
    for req_id in ctx.outline_reqs():
        row = ctx.matrix.get(req_id)
        if row and applies(row.get("condition"), ctx.employee) is False:
            out.append(F("V-CONDITION", "error", "Unsupported Requirement",
                         f"{req_id} applies only when {row['condition']['text']!r}, which is not true for this employee.",
                         req_id=req_id))
    return out


@rule("V-STAGE")
def stages(ctx, settings):
    out = []
    reqs = ctx.outline_reqs()
    for req_id, r in reqs.items():
        row = ctx.matrix.get(req_id)
        if row and r["due_stage"] != row["due_stage"]:
            stated = row.get("stage_source") == "text"
            out.append(F("V-STAGE", "warning" if stated else "info",
                         "Verified with Warning" if stated else "Verified",
                         f"{req_id} is scheduled for {r['due_stage']}; the source "
                         f"{'states' if stated else 'suggests'} {row['due_stage']}.", req_id=req_id))
    day1 = [k for k, r in reqs.items() if r["due_stage"] == "D1"]
    if len(day1) > ctx.day1_max_items:
        out.append(F("V-STAGE", "warning", "Verified with Warning",
                     f"{len(day1)} requirements are placed on Day 1 (limit {ctx.day1_max_items}).",
                     evidence={"day1": day1}))
    return out


@rule("V-SEQUENCE")
def sequence(ctx, _):
    out = []
    reqs, order = ctx.outline_reqs(), ctx.stage_order
    for req_id, prereq_id in ctx.prerequisites:
        if req_id in reqs and prereq_id in reqs:
            if order.get(reqs[prereq_id]["due_stage"], 0) > order.get(reqs[req_id]["due_stage"], 0):
                out.append(F("V-SEQUENCE", "warning", "Partially Verified",
                             f"{req_id} ({reqs[req_id]['due_stage']}) comes before its prerequisite {prereq_id} "
                             f"({reqs[prereq_id]['due_stage']}).", req_id=req_id))
        elif req_id in reqs and prereq_id not in reqs and prereq_id in ctx.matrix:
            out.append(F("V-SEQUENCE", "warning", "Partially Verified",
                         f"{req_id} depends on {prereq_id}, which is missing from the plan.", req_id=req_id))
    if ctx.employee.get("experience_level") == "Beginner":
        for _, item in ctx.items("task"):
            if item.get("difficulty") == "Advanced" and item.get("stage") in ("D1", "W1"):
                out.append(F("V-SEQUENCE", "warning", "Partially Verified",
                             "Advanced task scheduled in the first week for a beginner.", item_key=item["item_key"]))
    return out


def _item_text(item):
    c = item["content"]
    return c.get("question") or c.get("description") or c.get("activity") or c.get("situation") or c.get("text") or ""


@rule("V-DUPLICATE")
def duplicates(ctx, settings):
    out, threshold = [], settings.get("similarity", 0.9)
    for item_type in ("quiz_question", "task", "checklist", "scenario"):
        seen = []
        for _, item in ctx.items(item_type):
            text = " ".join(_item_text(item).lower().split())
            twin = next((k for k, t in seen if SequenceMatcher(None, text, t).ratio() >= threshold), None)
            if twin:
                out.append(F("V-DUPLICATE", "warning", "Verified with Warning",
                             f"Substantially duplicates {twin}.", item_key=item["item_key"],
                             evidence={"duplicate_of": twin}))
            seen.append((item["item_key"], text))
    for m_a in ctx.modules:
        for m_b in ctx.modules:
            if m_a["module_key"] < m_b["module_key"] and \
                    SequenceMatcher(None, m_a["title"].lower(), m_b["title"].lower()).ratio() >= threshold:
                out.append(F("V-DUPLICATE", "warning", "Verified with Warning",
                             f"Modules {m_a['module_key']} and {m_b['module_key']} have near-identical titles."))
    return out


@rule("V-QUIZ-SOURCE")
def quiz(ctx, settings):
    out, min_overlap = [], settings.get("min_word_overlap", 0.5)
    for _, item in ctx.items("quiz_question"):
        c = item["content"]
        source = ctx.sections.get((item.get("source_doc_id"), item.get("source_section_id")))
        if source is None:
            continue                                   # V-SOURCE already reports it
        options, correct = c.get("options", []), c.get("correct_options", [])
        if not correct or any(i >= len(options) or i < 0 for i in correct):
            out.append(F("V-QUIZ-SOURCE", "error", "Source Support Missing", "The correct answer index is invalid.",
                         item_key=item["item_key"]))
            continue
        source_facts = facts(source)
        if c.get("type") == "true_false":
            answer_true = options[correct[0]].strip().lower() == "true"
            missing = unsupported(c.get("question", ""), source)
            if answer_true and missing:
                out.append(F("V-QUIZ-SOURCE", "error", "Source Support Missing",
                             "The statement marked True contains facts not in the cited source.",
                             item_key=item["item_key"], evidence={"missing_facts": sorted(missing)}))
            continue
        for i in correct:
            text = options[i]
            missing = unsupported(text, source)
            if missing or (not facts(text) and overlap(text, source) < min_overlap and overlap(text, c.get("explanation", "")) < min_overlap):
                out.append(F("V-QUIZ-SOURCE", "error", "Source Support Missing",
                             f"The correct answer '{text[:80]}' is not supported by the cited section.",
                             item_key=item["item_key"], evidence={"missing_facts": sorted(missing)}))
        for i, text in enumerate(options):
            if i not in correct and facts(text) and facts(text) <= source_facts and \
                    not any(facts(options[j]) and facts(options[j]) <= source_facts for j in correct):
                out.append(F("V-QUIZ-SOURCE", "warning", "Verified with Warning",
                             f"Wrong option '{text[:60]}' matches the source better than the marked answer.",
                             item_key=item["item_key"]))
    return out


def _claims(item):
    """(field, text) pairs of generated text that may state facts."""
    c = item["content"]
    for f in ("text", "activity", "description", "expected_outcome", "completion_criteria", "situation", "explanation"):
        if c.get(f):
            yield f, c[f]
    for action in c.get("expected_actions", []):
        yield "expected_action", action


@rule("V-HALLUCINATION")
def hallucination(ctx, _):
    """Every number, amount and time in generated text must appear in the sources (the numeric-fact check).

      - fact in the cited section / the item's or module's requirements: supported
      - fact only elsewhere in the approved documents: warning (supported, but cited from the wrong place)
      - fact nowhere in the approved documents: error (possible hallucination)
    Scenario situations may contain illustrative details (room numbers, nights stayed), so facts that
    appear nowhere are a warning there rather than an error.
    """
    out = []
    everything = "\n".join(ctx.sections.values())
    for module, item in ctx.items():
        cited = ctx.sections.get((item.get("source_doc_id"), item.get("source_section_id")), "")
        related = " ".join(ctx.requirements[r]["chunk_text"] for r in
                           list(module.get("requirement_ids", [])) + list(item.get("requirement_ids", []))
                           if r in ctx.requirements)
        local = cited + "\n" + related
        for field, claim in _claims(item):
            missing = unsupported(claim, local)
            if not missing:
                continue
            absent = unsupported(" ".join(missing), everything)
            if absent and field != "situation":
                out.append(F("V-HALLUCINATION", "error", "Source Support Missing",
                             f"Possible hallucination: {', '.join(sorted(absent))} appears in no approved document.",
                             item_key=item["item_key"], evidence={"claim": claim[:300], "missing_facts": sorted(absent)}))
            elif absent:
                out.append(F("V-HALLUCINATION", "warning", "Verified with Warning",
                             f"Scenario detail {', '.join(sorted(absent))} is not from the sources (illustrative).",
                             item_key=item["item_key"], evidence={"claim": claim[:300], "missing_facts": sorted(absent)}))
            else:
                out.append(F("V-HALLUCINATION", "warning", "Verified with Warning",
                             f"{', '.join(sorted(missing))} is company policy, but not from the cited section.",
                             item_key=item["item_key"], evidence={"claim": claim[:300], "facts": sorted(missing)}))
            break
    return out


@rule("V-ASSESS")
def assessment(ctx, _):
    out = []
    for m in ctx.modules:
        assessments = [i for i in m["items"] if i["item_type"] == "assessment"]
        if m.get("content_ok", True) and not assessments:
            out.append(F("V-ASSESS", "warning", "Verified with Warning", f"Module {m['module_key']} has no assessment."))
        for a in assessments:
            total = sum(r.get("weight", 0) for r in a["content"].get("rubric", []))
            if total != 100:
                out.append(F("V-ASSESS", "warning", "Verified with Warning",
                             f"Rubric weights add up to {total}, not 100.", item_key=a["item_key"]))
    return out


@rule("V-CHECKLIST")
def checklist(ctx, _):
    out, links = [], {}
    for _, item in ctx.items("checklist"):
        for req_id in item.get("requirement_ids", []):
            links.setdefault(req_id, []).append(item["item_key"])
    for req_id, r in ctx.outline_reqs().items():
        row = ctx.matrix.get(req_id)
        if row and row["mandatory"] and row["req_type"] in ("Must Complete", "Must Acknowledge") and req_id not in links:
            out.append(F("V-CHECKLIST", "warning", "Verified with Warning",
                         f"{req_id} asks the employee to complete or acknowledge something but has no checklist item.",
                         req_id=req_id))
    return out


@rule("V-CONTRADICTION")
def contradiction(ctx, _):
    """Plan content that follows the losing side of a resolved conflict, or an unresolved one."""
    out = []
    for req_id in ctx.outline_reqs():
        info = ctx.conflicts.get(req_id)
        if not info:
            continue
        if info["type"] == "lost":
            out.append(F("V-CONTRADICTION", "error", "Contradiction Detected",
                         f"{req_id} was overridden by {info['winner']} ({info['conflict']}): {info['explanation']}",
                         req_id=req_id, evidence=info))
        elif info["type"] == "manual":
            out.append(F("V-CONTRADICTION", "warning", "Manual Review Required",
                         f"{req_id} conflicts with {info['other']} ({info['conflict']}) and no rule decides between them.",
                         req_id=req_id, evidence=info))
        elif info["type"] == "safety_override":
            out.append(F("V-CONTRADICTION", "warning", "Verified with Warning",
                         f"{req_id} applies because of the life-safety rule ({info['conflict']}): {info['explanation']}",
                         req_id=req_id, evidence=info))
    return out
