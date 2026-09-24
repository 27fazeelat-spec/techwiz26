"""Staff workspace: the admin home, the Terracotta theme switch and the Ctrl+K search endpoint."""
from flask import current_app

from tests.conftest import login


def test_admin_home_shows_the_pipeline_and_the_theme(corpus):
    client = current_app.test_client()
    login(client, "admin@aurelle.example")
    html = client.get("/dashboard/admin").get_data(as_text=True)
    assert "theme-terra" in html and "css/terra.css" in html and "js/workspace.js" in html
    assert "From policy to plan" in html and "Needs you" in html
    assert "data-cmdk-open" in html


def test_other_roles_keep_their_theme_until_moved(corpus):
    client = current_app.test_client()
    login(client, "leila.haddad@aurelle.example")
    html = client.get("/dashboard/me").get_data(as_text=True)
    assert "theme-terra" not in html and "css/terra.css" not in html


def test_search_finds_documents_and_requirements_for_staff(corpus):
    client = current_app.test_client()
    login(client, "admin@aurelle.example")
    data = client.get("/api/search?q=GDP").get_json()
    labels = {g["label"]: g["items"] for g in data["groups"]}
    assert labels["Documents"] and labels["Documents"][0]["code"].startswith("GDP-01")
    assert all(i["code"].startswith("R-GDP") or "GDP" in i["title"] for i in labels.get("Requirements", []))
    assert client.get("/api/search?q=a").get_json() == {"groups": []}          # too short to search


def test_search_respects_permissions(corpus):
    client = current_app.test_client()
    login(client, "leila.haddad@aurelle.example")                              # employees cannot browse policies
    data = client.get("/api/search?q=GDP").get_json()
    assert data == {"groups": []}
