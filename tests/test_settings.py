from urllib.parse import unquote, urlsplit

from config.settings import LOCAL_SQLITE, database_url, engine_options


def test_empty_url_uses_local_sqlite():
    assert database_url("") == LOCAL_SQLITE


def test_provider_urls_get_the_pg8000_driver():
    assert database_url("postgres://u:p@h:5432/d") == "postgresql+pg8000://u:p@h:5432/d"   # secret-scan: fake
    assert database_url("postgresql://u:p@h:5432/d") == "postgresql+pg8000://u:p@h:5432/d"   # secret-scan: fake


def test_unencoded_special_characters_in_password_are_encoded():
    url = database_url("postgresql://postgres:@pa#ss/w?rd@db.example.supabase.co:5432/postgres")   # secret-scan: fake
    parts = urlsplit(url)
    assert parts.hostname == "db.example.supabase.co" and parts.port == 5432
    assert parts.path == "/postgres"
    assert unquote(parts.password) == "@pa#ss/w?rd"


def test_already_encoded_password_is_left_alone():
    url = database_url("postgresql://postgres:%40pa%23ss@h:5432/d")   # secret-scan: fake
    assert urlsplit(url).password == "%40pa%23ss"


def test_sslmode_query_is_removed_and_tls_is_configured_for_remote_hosts():
    url = database_url("postgresql://u:p@db.example.com:5432/d?sslmode=require")   # secret-scan: fake
    assert "sslmode" not in url
    assert "ssl_context" in engine_options(url)["connect_args"]


def test_missing_ca_file_fails_loudly(monkeypatch):
    import pytest
    monkeypatch.setenv("DATABASE_SSL_ROOT_CERT", "config/does-not-exist.crt")
    with pytest.raises(RuntimeError, match="does not exist"):
        engine_options(database_url("postgresql://u:p@db.example.com:5432/d"))   # secret-scan: fake


def test_verification_is_on_by_default(monkeypatch):
    import ssl
    monkeypatch.delenv("DATABASE_SSL_ROOT_CERT", raising=False)
    ctx = engine_options(database_url("postgresql://u:p@db.example.com:5432/d"))["connect_args"]["ssl_context"]   # secret-scan: fake
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_local_postgres_does_not_force_tls():
    assert "connect_args" not in engine_options(database_url("postgresql://u:p@localhost:5432/d"))   # secret-scan: fake
