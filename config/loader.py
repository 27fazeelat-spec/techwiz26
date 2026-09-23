"""Load and sanity-check the YAML rule files in config/.

The app refuses to start with a malformed config: a clear error at boot is better
than a wrong decision at runtime.
"""
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).parent

REQUIRED_KEYS = {
    "permissions": ["roles"],
    "documents": ["categories", "departments", "limits"],
    "precedence": ["tiers", "rules"],
    "stages": ["stages"],
    "glossary": ["synonyms"],
    "genai": ["provider", "generation", "retry"],
    "extraction": ["modality", "types", "stages", "default_stage", "conditions", "competencies", "priority",
                   "assessment", "lineage"],
    "security_patterns": ["families", "encoded", "obfuscation"],
    "progress": ["pass_mark_percent", "max_quiz_attempts", "completion", "status_order"],
}


class ConfigError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def load_config(name):
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise ConfigError(f"missing config file: {path.name}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc
    missing = [k for k in REQUIRED_KEYS.get(name, []) if k not in data]
    if missing:
        raise ConfigError(f"{path.name} is missing keys: {', '.join(missing)}")
    return data


def validate_all():
    """Load every known config file; raises ConfigError on the first problem."""
    for name in REQUIRED_KEYS:
        load_config(name)
    tiers = load_config("precedence")["tiers"]
    unknown = set(load_config("documents")["categories"]) - set(tiers)
    if unknown:
        raise ConfigError(f"precedence.yaml has no tier for categories: {', '.join(sorted(unknown))}")
