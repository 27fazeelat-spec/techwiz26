"""Public pages shown before sign-in."""
from tests.conftest import login


def test_public_pages_render_without_signing_in(client):
    for url, text in [("/", b"prove"), ("/platform", b"One pipeline"), ("/trust", b"never decide"),
                      ("/about", b"Aurelle"), ("/login", b"Sign in")]:
        response = client.get(url)
        assert response.status_code == 200, url
        assert text in response.data, url


def test_signed_in_users_go_from_home_to_their_dashboard(client):
    login(client, "admin@aurelle.example")
    response = client.get("/")
    assert response.status_code == 302 and response.headers["Location"].endswith("/app")
    assert client.get("/app").status_code == 302                       # then on to the role's dashboard


def test_public_pages_make_no_unmeasured_claims(client):
    page = client.get("/").data.decode()
    assert "99.5" in page and "customers" not in page.lower() and "testimonial" not in page.lower()
