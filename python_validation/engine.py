"""Rule registry, validation context and the validate() entry point."""
import hashlib
import inspect
import time
from dataclasses import dataclass, field

from config.loader import load_config

RULES = {}


def rule(rule_id):
    def register(fn):
        RULES[rule_id] = fn
        return fn
    return register


@dataclass
class F:
    """A finding. status = the item/requirement status it implies."""
    rule_id: str
    severity: str            # error | warning | info
    status: str
    message: str
    item_key: str | None = None
    req_id: str | None = None
    evidence: dict = field(default_factory=dict)


@dataclass
class ValidationContext:
    employee: dict                  # profile incl. property dict (for conditions)
    role_code: str
    outline: dict                   # PlanOutline as dict
    modules: list                   # [{module_key, title, category, stage, content_ok, items: [...]}]
    matrix: dict                    # req_id -> row dict for this role
    requirements: dict              # req_id -> current requirement dict (any role)
    sections: dict                  # (doc_id, section_id) -> source text of active/expired documents
    doc_status: dict                # doc_id -> status of its current version
    prerequisites: list             # [(req_id, prerequisite_req_id)]
    stage_order: dict               # stage code -> index
    matrix_approved: bool = True
    day1_max_items: int = 12
    conflicts: dict = field(default_factory=dict)   # req_id -> {type: lost|manual|safety_override, ...}

    # ---- helpers used by several rules
    def items(self, *types):
        for m in self.modules:
            for item in m["items"]:
                if not types or item["item_type"] in types:
                    yield m, item

    def outline_reqs(self):
        return {r["requirement_id"]: r for r in self.outline.get("requirements", [])}

    def linked_requirements(self):
        """req_id -> item keys that reference it."""
        links = {}
        for _, item in self.items():
            for req_id in item.get("requirement_ids", []):
                links.setdefault(req_id, []).append(item["item_key"])
        return links


def ruleset_hash():
    from python_validation import rules as rules_module
    source = inspect.getsource(rules_module) + str(load_config("validation_rules"))
    return hashlib.sha256(source.encode()).hexdigest()


def validate(ctx):
    """Run every enabled rule. Returns (findings, duration_ms)."""
    from python_validation import rules as _  # noqa: F401  (registers the rules)
    cfg = load_config("validation_rules")["rules"]
    start = time.perf_counter()
    findings = []
    for rule_id, fn in RULES.items():
        settings = cfg.get(rule_id, {})
        if settings.get("enabled", True):
            findings.extend(fn(ctx, settings))
    return findings, int((time.perf_counter() - start) * 1000)
