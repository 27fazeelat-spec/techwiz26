"""Versioned prompt templates (SRS Steps 40-41).

Each template file starts with '# name:' and '# version:' header lines, then a '## SYSTEM' and a
'## USER' section. The SHA-256 of the file is recorded with every generation run, so any change to a
prompt is visible in the logs even if someone forgets to bump the version.
"""
import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, StrictUndefined

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "prompt_templates"
_env = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=False)


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    sha256: str
    system: str
    user: str

    def render(self, **context):
        return _env.from_string(self.system).render(**context).strip(), \
               _env.from_string(self.user).render(**context).strip()


@lru_cache(maxsize=None)
def load(name):
    path = TEMPLATE_DIR / f"{name}.j2"
    raw = path.read_text(encoding="utf-8")
    header = {}
    for line in raw.splitlines():
        if line.startswith("# ") and ":" in line:
            key, _, value = line[2:].partition(":")
            header[key.strip()] = value.strip()
        elif line.startswith("## "):
            break
    if "## SYSTEM" not in raw or "## USER" not in raw or "name" not in header or "version" not in header:
        raise ValueError(f"prompt template {path.name} must have name/version headers and SYSTEM/USER sections")
    system = raw.split("## SYSTEM", 1)[1].split("## USER", 1)[0]
    user = raw.split("## USER", 1)[1]
    return PromptTemplate(header["name"], header["version"], hashlib.sha256(raw.encode()).hexdigest(), system, user)
