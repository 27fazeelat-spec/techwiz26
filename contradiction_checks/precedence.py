"""Policy precedence (SRS Step 34). Rules and their order come from config/precedence.yaml.

  same_lineage      newer version of the same document wins
  life_safety       on injury / fire / evacuation / medical topics, a stricter lower-tier rule wins (with a warning)
  tier              the higher-authority tier (lower number) wins
  same_tier_manual  same tier, different documents: no automatic winner
"""
import re

from config.loader import load_config
from contradiction_checks.signals import stricter

TIER_NAMES = {1: "Policy / Compliance", 2: "SOP / Procedure", 3: "Role Description", 4: "Handbook", 5: "FAQ",
              6: "Informal guidance"}


def _describe(diffs):
    parts = []
    for d in diffs:
        if d["type"] == "number":
            parts.append(f"{d['unit']}: {', '.join(f'{v:g}' for v in d['left'])} vs {', '.join(f'{v:g}' for v in d['right'])}")
        elif d["type"] == "deadline":
            parts.append(f"deadline: {d['left']:g} vs {d['right']:g} minutes")
        elif d["type"] == "frequency":
            parts.append(f"frequency: every {d['left']:g} vs every {d['right']:g} months")
        else:
            parts.append(f"one {d['left']}, the other {d['right']}")
    return "; ".join(parts)


def _ref(r):
    return f"{r['doc_id']} v{r['version']} ({TIER_NAMES.get(r['tier'], 'tier ' + str(r['tier']))})"


def resolve(conflict):
    """Return {rule, winner (left|right|None), status, explanation}."""
    cfg = {r["id"]: r for r in load_config("precedence")["rules"]}
    a, b, diffs = conflict["left"], conflict["right"], conflict["differences"]
    what = _describe(diffs)

    if conflict["kind"] == "version":
        return {"rule": "same_lineage", "winner": "left", "status": "auto_resolved",
                "explanation": f"{a['doc_id']} v{a['version']} replaces v{b['version']} ({what}); the current version applies."}

    topics = cfg.get("life_safety", {}).get("topics", [])
    safety = any(re.search(rf"\b{re.escape(t)}", (a["text"] + " " + b["text"]).lower()) for t in topics)
    if safety and a["tier"] != b["tier"]:
        verdicts = {stricter(d) for d in diffs if stricter(d)}
        if len(verdicts) == 1:
            strict = verdicts.pop()
            lower = "left" if a["tier"] > b["tier"] else "right"
            if strict == lower:
                winner = conflict[strict]
                return {"rule": "life_safety", "winner": strict, "status": "auto_resolved_warning",
                        "explanation": f"Life-safety topic: the stricter rule in {_ref(winner)} applies even though "
                                       f"the other source ranks higher ({what}). The document owner should align the texts."}

    if a["tier"] != b["tier"]:
        winner = "left" if a["tier"] < b["tier"] else "right"
        w, l = conflict[winner], conflict["right" if winner == "left" else "left"]
        return {"rule": "tier", "winner": winner, "status": "auto_resolved",
                "explanation": f"{_ref(w)} outranks {_ref(l)} ({what}); the {w['doc_id']} rule applies."}

    return {"rule": "same_tier_manual", "winner": None, "status": "manual_review",
            "explanation": f"{_ref(a)} and {_ref(b)} have the same authority and disagree ({what}). "
                           "A reviewer must decide which rule applies."}
