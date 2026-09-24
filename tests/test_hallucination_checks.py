"""Topic support (hallucination challenge): the application refuses topics the approved documents do not cover."""
from flask import current_app

from hallucination_checks import assess
from tests.conftest import login

PASSAGES = [
    {"ref": "c1", "doc_id": "FLS-01", "section_id": "2.1", "text": "All employees must know the fire assembly point and evacuation route."},
    {"ref": "c2", "doc_id": "GDP-01", "section_id": "4.2", "text": "Passport scans must be deleted from the PMS within 7 days of check-out."},
    {"ref": "c3", "doc_id": "HBK-01", "section_id": "1.1", "text": "Uniforms are issued on the first day."},
]


def test_assess_decides_from_the_passages_alone():
    covered = assess("fire evacuation and assembly point", PASSAGES)
    assert covered.status == "supported" and covered.matches[0]["doc_id"] == "FLS-01"
    missing = assess("scuba diving instructor certification", PASSAGES)
    assert missing.status == "unsupported" and missing.matches == []
    partly = assess("passport scanning machine maintenance contract", PASSAGES)
    assert partly.status == "review"
    assert assess("the and of", PASSAGES).status == "unsupported"                      # nothing to look for


def test_topic_check_page_on_the_real_documents(corpus):
    client = current_app.test_client()
    login(client, "training@aurelle.example")
    covered = client.get("/topics?topic=fire assembly point evacuation").get_data(as_text=True)
    assert "Covered by the approved documents" in covered and "FLS-01" in covered
    refused = client.get("/topics?topic=scuba diving instructor certification").get_data(as_text=True)
    assert "Not covered: nothing will be generated" in refused
    client.post("/logout")
    login(client, "leila.haddad@aurelle.example")
    assert client.get("/topics?topic=fire").status_code == 403                         # employees do not browse sources
