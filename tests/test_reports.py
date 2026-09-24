"""Reports and exports are computed from stored data (SRS FR lxi-lxii, deliverables 1.10.6 and 1.10.8)."""
import csv
import io

from flask import current_app
from sqlalchemy import select

from database import db
from database.models import AuditLog, ComparisonRow
from src.services import reports
from tests.conftest import login
from tests.test_review import fresh_plan


def test_every_report_builds_and_exports_in_every_format(corpus):
    fresh_plan()
    for name in reports.REPORTS:
        table = reports.build(name)
        assert table.columns and all(len(r) == len(table.columns) for r in table.rows), name
        data = reports.to_csv(table)
        parsed = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        assert parsed[0] == table.columns and len(parsed) == len(table.rows) + 1
        assert reports.to_xlsx(table)[:2] == b"PK"                      # a zip container, i.e. a real .xlsx
        assert reports.to_pdf(table)[:4] == b"%PDF"


def test_comparison_report_has_at_least_100_rows_and_matches_the_database(corpus):
    plan = fresh_plan()
    table = reports.build("comparison")
    assert len(table.rows) >= 100                                       # SRS deliverable 1.10.6
    from src.services.review import latest_run
    stored = db.session.scalars(select(ComparisonRow).where(ComparisonRow.validation_run_id == latest_run(plan).id)).all()
    mine = [r for r in table.rows if r[0] == f"{plan.plan_code} v{plan.version}"]
    assert len(mine) == len(stored)                                     # nothing invented, nothing dropped


def test_validation_report_uses_the_stored_scores(corpus):
    plan = fresh_plan()
    row = next(r for r in reports.build("validation").rows if r[0] == f"{plan.plan_code} v{plan.version}")
    assert row[5] == plan.status and row[6] == round(plan.score_coverage, 1)


def test_role_filter_and_manager_scope(corpus):
    fresh_plan()
    assert all(r[2] == "FOA" for r in reports.build("comparison", role="FOA").rows)
    assert reports.build("comparison", role="HRE").rows == [] or all(r[2] == "HRE" for r in reports.build("comparison", role="HRE").rows)
    client = current_app.test_client()
    login(client, "training@aurelle.example")
    assert client.get("/reports").status_code == 200
    assert client.get("/reports/comparison").status_code == 200
    response = client.get("/reports/validation.xlsx")
    assert response.status_code == 200 and response.data[:2] == b"PK"
    assert db.session.scalar(select(AuditLog).where(AuditLog.action == "report.exported", AuditLog.entity_id == "validation"))
    client.post("/logout")
    login(client, "omar.siddiqui@aurelle.example")                      # line manager: team reports only
    assert client.get("/reports/progress").status_code == 200
    assert client.get("/reports/comparison").status_code == 404
    progress_rows = reports.build("progress", employee_ids=[1]).rows
    assert all(r[1] == "E001" for r in progress_rows)
    client.post("/logout")
    login(client, "leila.haddad@aurelle.example")
    assert client.get("/reports").status_code == 403


def test_employee_filters_and_plan_comparison(corpus):
    from src.services.planning import compare_plans
    a = fresh_plan()
    b = fresh_plan(drop_first_mandatory=True)
    result = compare_plans(a, b)
    assert result["only_a"] and not result["only_b"] and result["overlap"] < 100
    client = current_app.test_client()
    login(client, "training@aurelle.example")
    page = client.get("/employees?role=FOA").data
    assert b"Leila Haddad" in page and b"Grace Tan" not in page
    assert b"Grace Tan" not in client.get("/employees?q=leila").data
    assert client.get("/employees?progress=On+Track&result=Verified").status_code == 200
    assert client.get(f"/plans/compare?a={a.id}&b={b.id}").status_code == 200


def test_a_failed_attempt_never_hides_the_last_good_plan(corpus):
    from database.models import Plan
    good = fresh_plan()
    bad = Plan(plan_code=good.plan_code, version=good.version + 1, employee_id=good.employee_id,
               job_role_id=good.job_role_id, matrix_version_id=good.matrix_version_id, status="Failed",
               error="auth: 403 PERMISSION_DENIED", created_by="test")
    db.session.add(bad)
    db.session.commit()
    client = current_app.test_client()
    login(client, "training@aurelle.example")
    page = client.get("/employees?q=E001").data.decode()
    assert f"{good.plan_code} v{good.version}" in page and f"Last attempt failed (v{bad.version})" in page
