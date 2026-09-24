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


def test_each_role_lands_on_its_own_home_with_workspace_branding(client):
    homes = {"admin@aurelle.example": "/dashboard/admin", "training@aurelle.example": "/dashboard/plans",
             "evaluator@aurelle.example": "/dashboard/review", "omar.siddiqui@aurelle.example": "/dashboard/team",
             "leila.haddad@aurelle.example": "/dashboard/me"}
    for email, home in homes.items():
        login(client, email)
        response = client.get("/app")
        assert response.headers["Location"].endswith(home), email
        page = client.get(home)
        assert page.status_code == 200, email
        html = page.data.decode()
        assert "Aurelle" in html and "Powered by SkillSprint" in html
        client.post("/logout")


def test_sidebar_offers_only_each_roles_pages(client):
    login(client, "leila.haddad@aurelle.example")
    html = client.get("/dashboard/me").data.decode()
    assert "My onboarding" in html and "Review queue" not in html and "Documents" not in html
    client.post("/logout")
    login(client, "evaluator@aurelle.example")
    html = client.get("/dashboard/review").data.decode()
    assert "Review queue" in html and "Job roles" not in html
