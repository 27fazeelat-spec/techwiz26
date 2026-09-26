"""The document library: one card per document, status and department charts, version timeline, plain words."""
import json
import re

import pytest

from tests.conftest import SAMPLES, TODAY, login


@pytest.fixture()
def library(app):
    """Two versions of one SOP and a memo with a planted attack."""
    from src.services.ingestion import ingest_document
    with app.app_context():
        for name in ("SOP-FO-01_v1.0.docx", "SOP-FO-01_v2.0.docx", "MEM-01_v1.0.docx"):
            form = {"category": "Informal Guidance"} if name.startswith("MEM") else None
            assert ingest_document((SAMPLES / name).read_bytes(), name, form=form, today=TODAY).ok
    client = app.test_client()
    login(client, "admin@aurelle.example")
    return client


def test_library_shows_one_card_per_document_with_charts(library):
    page = library.get("/documents/").get_data(as_text=True)
    cards = re.findall(r'<a class="libcard" href="([^"]+)"', page)
    assert len(cards) == 2                                              # three files, two documents
    assert "/documents/SOP-FO-01/2.0" in cards                          # the card opens the version in force
    donut = json.loads(re.search(r'data-donut="([^"]+)"', page).group(1).replace("&#34;", '"'))
    assert {d["key"]: d["value"] for d in donut} == {"active": 2, "superseded": 1}
    assert {d["label"] for d in donut} == {"In force", "Older version"}
    assert 'data-set-filter="dept:Front Office"' in page
    assert "Suspicious text found and blocked" in page                      # the memo's attack, in plain words
    assert 'data-libpane="table" hidden' in page and ">Chunks</th>" in page   # the full table is one click away


def test_document_page_explains_versions_and_rules(library):
    page = library.get("/documents/SOP-FO-01/2.0").get_data(as_text=True)
    stops = re.findall(r'<li class="vline__item ?([^"]*)"', page)
    assert len(stops) == 2 and stops[1].strip() == "is-current"         # oldest first, this version highlighted
    assert re.search(r'class="is-(add|change|remove)"', page)           # what v2.0 changed
    assert "What it asks people to do" in page and 'class="rulelist__kind is-must">Must<' in page
    assert '<details class="expert">' in page and "SHA-256" in page     # technical detail kept, folded away
    memo = library.get("/documents/MEM-01/1.0").get_data(as_text=True)
    assert "Suspicious text blocked" in memo


def test_upload_page_and_the_result_right_after_uploading(app):
    import io
    client = app.test_client()
    login(client, "admin@aurelle.example")
    page = client.get("/documents/upload").get_data(as_text=True)
    assert "data-dropzone" in page and 'class="dropzone__input"' in page
    assert '<details class="expert" >' in page                          # optional details folded away
    name = "SOP-FO-01_v2.0.docx"
    response = client.post("/documents/upload", data={"file": (io.BytesIO((SAMPLES / name).read_bytes()), name)},
                           content_type="multipart/form-data")
    assert response.status_code == 302 and response.headers["Location"].endswith("?uploaded=1")
    result = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Your document was added" in result
    rules = len(re.findall(r'class="rulelist__kind', result))
    assert rules and re.search(r"<b>Found the rules</b>\s*<span>\d+ rules", result)
    assert "Your document was added" not in client.get("/documents/SOP-FO-01/2.0").get_data(as_text=True)
