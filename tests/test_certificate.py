"""Learner pages and the onboarding certificate: issued only when every step is done, downloadable, publicly verifiable."""
from datetime import datetime

import pytest
from flask import current_app
from sqlalchemy import delete

from database import db
from database.models import Certificate
from src.services import progress
from tests.conftest import TODAY, login
from tests.test_planning_pipeline import leila
from tests.test_progress import assigned, rows
from tests.test_review import ACTOR


def fresh():
    db.session.execute(delete(Certificate))
    db.session.commit()
    return assigned()


def finish(plan):
    for r in rows(plan):
        r.status, r.completed_at = "completed", datetime(2026, 1, 1)
        if r.plan_item.item_type in ("quiz_question", "assessment"):
            r.score = 90
    db.session.commit()


def test_certificate_needs_every_step_done(corpus):
    plan = fresh()
    with pytest.raises(progress.ProgressError):
        progress.issue_certificate(leila(), plan, TODAY, ACTOR)
    finish(plan)
    cert = progress.issue_certificate(leila(), plan, TODAY, ACTOR)
    assert cert.code.startswith("AUR-") and cert.details["items"] == len(rows(plan))
    assert progress.issue_certificate(leila(), plan, TODAY, ACTOR).id == cert.id      # issued once
    pdf = progress.certificate_pdf(cert, {"name": "Aurelle", "tagline": "Hotels & Residences"}, None, "http://x/verify")
    assert pdf[:4] == b"%PDF"


def test_learner_pages_certificate_download_and_verify(corpus):
    plan = fresh()
    client = current_app.test_client()
    login(client, "leila.haddad@aurelle.example")
    for url in ("/learn", "/learn/progress", "/learn/assessments", "/learn/resources", "/learn/calendar"):
        assert client.get(url).status_code == 200, url
    page = client.get("/learn/certificate").data
    assert b"to go" in page and b"Claim certificate" not in page
    assert client.get("/learn/certificate.pdf").status_code == 404                 # nothing issued yet
    client.post("/learn/certificate")
    assert progress.certificate_for(leila(), plan) is None                          # not complete: no certificate

    finish(plan)
    assert b"Claim certificate" in client.get("/learn/certificate").data
    client.post("/learn/certificate")
    cert = progress.certificate_for(leila(), plan)
    assert cert is not None
    pdf = client.get("/learn/certificate.pdf")
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"
    client.post("/logout")
    assert b"Valid certificate" in client.get(f"/verify/{cert.code}").data           # public, no login needed
    assert client.get("/verify/AUR-00000000").status_code == 404
