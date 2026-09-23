"""Environment-driven settings. Secrets come from .env or the host's secret store."""
import os
import re
import ssl
from datetime import date
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
LOCAL_SQLITE = f"sqlite:///{(ROOT / 'instance' / 'skillsprint.db').as_posix()}"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _encode_credentials(url):
    """Percent-encode the user and password if they contain characters such as @ # / ? :

    Passwords copied from a hosting dashboard are often pasted unencoded. The host part never
    contains '@', so the last '@' reliably separates credentials from host.
    """
    scheme, sep, rest = url.partition("://")
    if not sep or "@" not in rest:
        return url
    userinfo, _, hostpart = rest.rpartition("@")
    user, colon, password = userinfo.partition(":")

    def encode(value):
        already_encoded = re.search(r"%[0-9A-Fa-f]{2}", value) and unquote(value) != value
        return value if already_encoded else quote(value, safe="")

    return f"{scheme}://{encode(user)}{colon}{encode(password)}@{hostpart}"


def database_url(raw=None):
    """PostgreSQL via pg8000 when DATABASE_URL is set; otherwise a local SQLite file.

    Providers hand out 'postgres://' or 'postgresql://' URLs; SQLAlchemy needs the driver named.
    libpq-only query options (sslmode) are removed here: SSL is configured in engine_options().
    """
    url = (os.getenv("DATABASE_URL", "") if raw is None else raw).strip()
    if not url:
        return LOCAL_SQLITE
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+pg8000://" + url[len(prefix):]
    url = _encode_credentials(url)
    return re.sub(r"([?&])sslmode=[^&]*&?", r"\1", url).rstrip("?&")


def root_cert_path():
    """CA file for verifying the database server (relative paths are relative to the project root)."""
    value = os.getenv("DATABASE_SSL_ROOT_CERT", "").strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise RuntimeError(f"DATABASE_SSL_ROOT_CERT points to '{value}', but that file does not exist.")
    return str(path)


def verified_context(cafile=None):
    """TLS context that verifies the certificate chain, expiry and hostname.

    Python 3.13+ also enables VERIFY_X509_STRICT by default, which additionally rejects CA
    certificates without a keyUsage extension. Some providers' long-lived roots (including
    "Supabase Root 2021 CA") predate that convention, so that single strictness flag is cleared.
    Chain-of-trust, validity-period and hostname checks all remain in force.
    """
    context = ssl.create_default_context(cafile=cafile)
    context.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    return context


def engine_options(url):
    """Engine settings for a given URL.

    Remote PostgreSQL connections always use TLS with full certificate verification: against
    DATABASE_SSL_ROOT_CERT when set (Supabase's own CA), otherwise the system trust store.
    There is deliberately no option to switch verification off.
    """
    options = {"pool_pre_ping": True}
    if not url.startswith("postgresql+pg8000://"):
        return options
    options.update(pool_size=5, max_overflow=5, pool_recycle=1800)
    if (urlsplit(url).hostname or "") in LOCAL_HOSTS:
        return options
    options["connect_args"] = {"ssl_context": verified_context(root_cert_path()), "timeout": 15}
    return options


class Settings:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-not-secret")
    SQLALCHEMY_DATABASE_URI = database_url()
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "15"))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
    SEED_PASSWORD = os.getenv("SEED_PASSWORD", "")
    TODAY_OVERRIDE = os.getenv("SKILLSPRINT_TODAY", "")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 8 * 60 * 60  # one working shift


def today(app_config=None):
    """Business date. Overridable so demos and tests are reproducible."""
    override = (app_config or {}).get("TODAY_OVERRIDE") or Settings.TODAY_OVERRIDE
    return date.fromisoformat(override) if override else date.today()
