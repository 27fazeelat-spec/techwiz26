"""Each validation rule on minimal hand-built plans."""
from python_validation import ValidationContext, validate
from python_validation.statuses import plan_status, scores
from comparison_engine import compare

STAGES = {"D1": 0, "W1": 1, "W2": 2, "D30": 3}


def ctx(outline_reqs, items, matrix=None, employee=None, prerequisites=(), approved=True):
    matrix = matrix if matrix is not None else {
        "R-A-01-001": {"mandatory": True, "priority": "High", "due_stage": "D1", "stage_source": "text",
                       "competency": "Fire & Life Safety", "req_type": "Must Complete", "assessment_requirement": "Checklist",
                       "condition": None, "source_doc_id": "A-01", "source_section_id": "1.1", "source_status": "active",
                       "text": "Staff must attend fire orientation on Day 1."},
        "R-A-01-002": {"mandatory": True, "priority": "High", "due_stage": "W1", "stage_source": "default",
                       "competency": "Food Safety", "req_type": "Must Know", "assessment_requirement": "Quiz",
                       "condition": {"field": "property.country", "op": "eq", "value": "Malaysia", "text": "At Malaysian properties"},
                       "source_doc_id": "A-01", "source_section_id": "1.2", "source_status": "active",
                       "text": "At Malaysian properties, hot food must be held at 65 °C."}}
    requirements = {k: {"doc_id": v["source_doc_id"], "section_id": v["source_section_id"], "text": v["text"],
                        "mandatory": v["mandatory"], "doc_status": "active", "chunk_text": v["text"]}
                    for k, v in matrix.items()}
    requirements["R-B-01-001"] = {"doc_id": "B-01", "section_id": "2.1", "text": "Finance must reconcile daily.",
                                  "mandatory": True, "doc_status": "active", "chunk_text": "Finance must reconcile daily."}
    sections = {(r["doc_id"], r["section_id"]): r["chunk_text"] for r in requirements.values()}
    module = {"module_key": "M01", "title": "Safety", "category": "Fire & Life Safety", "stage": "D1",
              "content_ok": True, "items": items, "requirement_ids": [r["requirement_id"] for r in outline_reqs]}
    return ValidationContext(employee=employee or {"property": {"country": "UAE"}, "experience_level": "Beginner"},
                             role_code="FOA", outline={"requirements": outline_reqs}, modules=[module], matrix=matrix,
                             requirements=requirements, sections=sections, doc_status={"A-01": "active"},
                             prerequisites=list(prerequisites), stage_order=STAGES, matrix_approved=approved)


def req(rid, doc="A-01", section="1.1", stage="D1", mandatory=True):
    return {"requirement_id": rid, "mandatory": mandatory, "priority": "High", "due_stage": stage, "category": "Fire & Life Safety",
            "module_key": "M01", "source_document_id": doc, "source_section_id": section}


def item(key, item_type, rids, content, doc="A-01", section="1.1"):
    return {"item_key": key, "item_type": item_type, "stage": "D1", "difficulty": "Beginner", "source_doc_id": doc,
            "source_section_id": section, "content": content, "requirement_ids": rids}


RUBRIC = {"rubric": [{"weight": 100}], "requirement_ids": []}
GOOD_ITEMS = [item("I.C01", "checklist", ["R-A-01-001"], {"activity": "Attend fire orientation"}),
              item("I.X01", "assessment", ["R-A-01-001"], RUBRIC)]


def rules(findings):
    return {(f.rule_id, f.severity) for f in findings}


def test_clean_plan_is_verified():
    c = ctx([req("R-A-01-001")], GOOD_ITEMS)
    findings, _ = validate(c)
    assert plan_status(findings) == "Verified"
    s = scores(c, findings, compare(c, {}))
    assert s["coverage"] == 100.0 and s["traceability"] == 100.0


def test_missing_mandatory_requirement_makes_plan_incomplete():
    c = ctx([], [item("I.X01", "assessment", [], RUBRIC)])
    findings, _ = validate(c)
    assert ("V-COVERAGE", "error") in rules(findings) and plan_status(findings) == "Incomplete"


def test_condition_not_met_is_not_expected_but_flagged_when_included():
    c = ctx([req("R-A-01-001"), req("R-A-01-002", section="1.2", stage="W1")], GOOD_ITEMS)
    findings, _ = validate(c)
    assert any(f.rule_id == "V-CONDITION" and f.req_id == "R-A-01-002" for f in findings)


def test_other_roles_requirement_and_unknown_id():
    c = ctx([req("R-A-01-001"), req("R-B-01-001", doc="B-01", section="2.1"), req("R-Z-99-001")], GOOD_ITEMS)
    findings, _ = validate(c)
    assert any(f.rule_id == "V-ROLE" and f.req_id == "R-B-01-001" for f in findings)
    assert any(f.rule_id == "V-REQ-ID" and f.req_id == "R-Z-99-001" for f in findings)


def test_invented_number_is_a_hallucination():
    items = GOOD_ITEMS + [item("I.O01", "objective", ["R-A-01-001"], {"text": "Hold food at 63 °C."})]
    findings, _ = validate(ctx([req("R-A-01-001")], items))
    assert any(f.rule_id == "V-HALLUCINATION" and f.severity == "error" and "63 °c" in f.message for f in findings)


def test_nonexistent_cited_section():
    items = GOOD_ITEMS + [item("I.C02", "checklist", ["R-A-01-001"], {"activity": "x"}, section="9.9")]
    findings, _ = validate(ctx([req("R-A-01-001")], items))
    assert any(f.rule_id == "V-SOURCE" and f.item_key == "I.C02" for f in findings)


def test_quiz_answer_must_be_supported():
    q = {"type": "multiple_choice", "question": "When?", "options": ["Within Week 2", "On Day 1"], "correct_options": [0],
         "explanation": "Orientation happens later."}
    items = GOOD_ITEMS + [item("I.Q01", "quiz_question", ["R-A-01-001"], q)]
    findings, _ = validate(ctx([req("R-A-01-001")], items))
    assert any(f.rule_id == "V-QUIZ-SOURCE" and f.item_key == "I.Q01" for f in findings)


def test_rubric_weights_and_day1_overload():
    bad_rubric = [item("I.X01", "assessment", [], {"rubric": [{"weight": 50}], "requirement_ids": []}),
                  item("I.C01", "checklist", ["R-A-01-001"], {"activity": "Attend fire orientation"})]
    findings, _ = validate(ctx([req("R-A-01-001")], bad_rubric))
    assert any(f.rule_id == "V-ASSESS" for f in findings)


def test_prerequisite_scheduled_after_dependent():
    matrix_reqs = [req("R-A-01-001", stage="W1"), req("R-A-01-002", section="1.2", stage="D1")]
    c = ctx(matrix_reqs, GOOD_ITEMS, employee={"property": {"country": "Malaysia"}},
            prerequisites=[("R-A-01-002", "R-A-01-001")])
    findings, _ = validate(c)
    assert any(f.rule_id == "V-SEQUENCE" for f in findings)


def test_draft_matrix_blocks_verification():
    findings, _ = validate(ctx([req("R-A-01-001")], GOOD_ITEMS, approved=False))
    assert plan_status(findings) == "Manual Review Required"


def test_comparison_explains_disagreement():
    c = ctx([req("R-A-01-001", stage="W2")], GOOD_ITEMS)
    rows = compare(c, {})
    row = next(r for r in rows if r["req_id"] == "R-A-01-001")
    assert not row["fields"]["due_stage"]["match"] and "due stage" in row["explanation"]
