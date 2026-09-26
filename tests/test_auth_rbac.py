from tests.conftest import login


def test_anonymous_users_are_sent_to_login(client):
    response = client.get("/documents/")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_login_with_correct_password(client):
    response = login(client, "admin@aurelle.example")
    assert response.status_code == 302
    assert client.get("/dashboard/admin").status_code == 200


def test_wrong_password_gives_a_generic_message(client):
    response = login(client, "admin@aurelle.example", "wrong")
    assert response.status_code == 200
    assert b"Email or password is incorrect." in response.data


def test_account_locks_after_five_failed_attempts(client):
    for _ in range(5):
        login(client, "training@aurelle.example", "wrong")
    response = login(client, "training@aurelle.example")      # correct password, but locked
    assert b"Too many failed attempts" in response.data


def test_employee_cannot_open_documents(client):
    login(client, "leila.haddad@aurelle.example")
    assert client.get("/documents/").status_code == 403
    assert client.get("/dashboard/me").status_code == 200


def test_reviewer_can_view_but_not_upload(client):
    login(client, "evaluator@aurelle.example")
    assert client.get("/documents/").status_code == 200
    assert client.get("/documents/upload").status_code == 403


def test_manager_sees_only_their_team(client):
    login(client, "omar.siddiqui@aurelle.example")
    page = client.get("/dashboard/team").data
    assert b"Leila Haddad" in page and b"Arjun Menon" not in page


def test_logout_requires_post(client):
    login(client, "admin@aurelle.example")
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 302


def test_an_expired_form_token_still_signs_out(app, client):
    login(client, "admin@aurelle.example")
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        # no token, as when a page sat open too long: the form goes back to its page to try again
        stale = client.post("/documents/upload", headers={"Referer": "http://localhost/documents"})
        assert stale.status_code == 302 and stale.headers["Location"].endswith("/documents")
        assert client.post("/documents/upload", headers={"Referer": "https://evil.example/x"}).headers["Location"] == "/app"
        out = client.post("/logout")                      # signing out works even without a token
        assert out.status_code == 302 and "/login" in out.headers["Location"]
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
    assert client.get("/app").status_code == 302              # really signed out


def test_healthz(client):
    assert client.get("/healthz").get_json()["database"] is True
