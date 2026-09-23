"""Full generate -> validate pipeline on the real sample corpus, with a TEST-ONLY scripted provider."""
from sqlalchemy import select

from database import db
from database.models import (ComparisonRow, Employee, GenerationRun, MatrixVersion, PlanItem, PlanItemRequirement,
                             ValidationRun)
from src.services.planning import compose_modules, generate_plan
from tests.fakes import ScriptedProvider

CONFIG = {"GEMINI_API_KEY": "test", "GEMINI_MODEL": ""}


def ensure_approved_matrix():
    from src.services.matrix import approve, build_draft
    if not db.session.scalar(select(MatrixVersion).where(MatrixVersion.status == "approved")):
        approve(build_draft({"email": "test"}).version_no, {"email": "test"})


def leila():
    return db.session.scalar(select(Employee).where(Employee.employee_code == "E001"))


def test_pipeline_stores_plan_runs_validation_and_comparison(corpus):
    ensure_approved_matrix()
    provider = ScriptedProvider()
    plan = generate_plan(leila(), {"email": "test"}, CONFIG, provider=provider)
    assert plan.status not in ("Failed", "generating")
    outline_runs = db.session.scalars(select(GenerationRun).where(GenerationRun.plan_id == plan.id,
                                                                   GenerationRun.phase == "outline")).all()
    assert len(outline_runs) >= 2                                     # sharded Phase 1
    assert all(r.prompt_sha256 and r.raw_response for r in outline_runs)
    assert plan.modules and all(m.content_ok for m in plan.modules)
    run = db.session.scalar(select(ValidationRun).where(ValidationRun.plan_id == plan.id))
    rows = db.session.scalars(select(ComparisonRow).where(ComparisonRow.validation_run_id == run.id)).all()
    assert len(rows) >= 50
    assert plan.score_coverage >= 80 and plan.score_traceability >= 90
    linked = db.session.scalar(select(PlanItemRequirement).join(PlanItem).where(PlanItem.module_id == plan.modules[0].id))
    assert linked is not None                                         # items trace back to requirement rows
    # the scripted provider includes every clause, so conditional and other-role requirements are caught
    assert any(f.rule_id == "V-CONDITION" and f.severity == "error" for f in run.findings)


def test_validation_catches_a_dropped_requirement_and_an_invented_fact(corpus):
    ensure_approved_matrix()
    provider = ScriptedProvider(drop_first_mandatory=True, invent_fact=True)
    plan = generate_plan(leila(), {"email": "test"}, CONFIG, provider=provider)
    run = db.session.scalar(select(ValidationRun).where(ValidationRun.plan_id == plan.id))
    assert plan.status in ("Incomplete", "Unsupported", "Contradictory")
    assert any(f.rule_id == "V-HALLUCINATION" and "63 °c" in f.message for f in run.findings)


def test_modules_are_grouped_deterministically():
    reqs = [{"requirement_id": f"R-{i}", "category": cat, "due_stage": stage}
            for i, (cat, stage) in enumerate([("Fire & Life Safety", "D1"), ("Fire & Life Safety", "D1"),
                                              ("Data Privacy", "W1"), ("Data Privacy", "W1"), ("HR Essentials", "W2")])]
    modules, assigned = compose_modules(reqs, max_modules=8, min_size=2)
    assert [m["module_key"] for m in modules] == ["M01", "M02"]
    assert modules[0]["stage"] == "D1"
    assert all(r["module_key"] for r in assigned) and len(assigned) == 5


def test_consistency_check_compares_structured_sets(corpus):
    from src.services.planning import run_consistency
    ensure_approved_matrix()
    provider = ScriptedProvider()
    plan = generate_plan(leila(), {"email": "test"}, CONFIG, provider=provider)
    run_consistency(plan, CONFIG, provider=provider)
    assert plan.consistency["runs"] == 3                  # the plan's own outline + 2 re-runs
    assert plan.score_generation_consistency == 100.0     # a deterministic provider is perfectly consistent
    assert set(plan.consistency["dimensions"]) == {"mandatory_requirements", "sources", "module_categories", "due_stages"}
