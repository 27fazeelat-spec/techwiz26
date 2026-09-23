"""Structural rules from documentation/02_Architecture.md."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# SRS 1.8.14: GenAI must not replace validation, business rules, traceability or security.
GENAI_FREE_PACKAGES = ["document_validation", "document_processing", "python_validation", "comparison_engine",
                       "hallucination_checks", "contradiction_checks", "role_matrix", "security"]
GENAI_IMPORT = re.compile(r"^\s*(from|import)\s+(google\.genai|google\.generativeai|genai_pipeline|openai|anthropic)\b", re.M)
SECRET = re.compile(
    r"(AIza[0-9A-Za-z_\-]{30,}"                              # Google API keys
    r"|AQ\.[0-9A-Za-z_\-]{20,}"                              # Google AI Studio keys
    r"|sk-[A-Za-z0-9]{20,}"
    r"|(postgres(ql)?(\+\w+)?|mongodb(\+srv)?)://[^<\s:/]+:[^<\s@]+@"   # credentials inside a connection URL
    r"|^(GEMINI_API_KEY|SECRET_KEY)=(?!change-me\s*$)\S+)", re.M)


def test_validation_packages_never_import_genai():
    offenders = []
    for package in GENAI_FREE_PACKAGES:
        for path in (ROOT / package).rglob("*.py") if (ROOT / package).exists() else []:
            if GENAI_IMPORT.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders


FAKE_MARKER = "secret-scan: fake"   # explicit opt-out for deliberately fake example credentials


def test_no_secrets_committed():
    offenders = []
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in (".py", ".yaml", ".yml", ".json", ".md", ".html", ".js", ".example") \
                and ".git" not in path.parts and path.name != ".env":
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                if FAKE_MARKER not in line and SECRET.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{n}")
    assert not offenders
