"""Item, requirement and plan statuses plus scores, derived only from findings (architecture 7.4)."""
from config.loader import load_config
from python_validation.rules import FACT_ITEMS, _expected
from role_matrix.conditions import applies

BLOCKING_TRACE = {"Source Support Missing", "Unsupported Requirement"}


def _order():
    return load_config("validation_rules")["item_status_order"]


def worst(statuses):
    order = _order()
    return min(statuses, key=order.index) if statuses else "Verified"


def item_statuses(ctx, findings):
    by_item = {}
    for f in findings:
        if f.item_key and f.severity != "info":
            by_item.setdefault(f.item_key, []).append(f.status)
    return {item["item_key"]: worst(by_item.get(item["item_key"], [])) for _, item in ctx.items()}


def requirement_statuses(ctx, findings):
    by_req = {}
    for f in findings:
        if f.req_id and f.severity != "info":
            by_req.setdefault(f.req_id, []).append(f.status)
    keys = set(ctx.outline_reqs()) | {r for r, row in ctx.matrix.items() if applies(row.get("condition"), ctx.employee)}
    return {k: worst(by_req.get(k, [])) for k in keys}


def plan_status(findings):
    statuses = {f.status for f in findings if f.severity != "info"}
    if "Contradiction Detected" in statuses:
        return "Contradictory"
    if "Requirement Missing" in statuses:
        return "Incomplete"
    if statuses & {"Unsupported Requirement", "Source Support Missing"}:
        return "Unsupported"
    if "Manual Review Required" in statuses:
        return "Manual Review Required"
    if statuses - {"Verified"}:
        return "Verified with Warning"
    return "Verified"


def scores(ctx, findings, comparison):
    expected, _ = _expected(ctx)
    mandatory = [r for r, row in expected.items() if row["mandatory"]]
    missing = {f.req_id for f in findings if f.rule_id == "V-COVERAGE" and f.status == "Requirement Missing"}
    covered = [r for r in mandatory if r not in missing]

    bad_items = {f.item_key for f in findings if f.item_key and f.status in BLOCKING_TRACE}
    traced_items = [(m, i) for m, i in ctx.items(*FACT_ITEMS, "objective")]
    ok = [i for _, i in traced_items if i["item_key"] not in bad_items
          and all(r in ctx.requirements for r in i.get("requirement_ids", [])) and i.get("requirement_ids")]
    mandatory_items = [i for _, i in traced_items if any(ctx.matrix.get(r, {}).get("mandatory") for r in i.get("requirement_ids", []))]
    mandatory_ok = [i for i in mandatory_items if i in ok]

    compared = sum(len(row["fields"]) for row in comparison)
    matched = sum(1 for row in comparison for f in row["fields"].values() if f["match"])
    pct = lambda a, b: round(100.0 * a / b, 1) if b else 100.0
    return {
        "coverage": pct(len(covered), len(mandatory)),
        "mandatory_expected": len(mandatory), "mandatory_covered": len(covered),
        "traceability": pct(len(ok), len(traced_items)),
        "traceability_mandatory": pct(len(mandatory_ok), len(mandatory_items)),
        "requirement_consistency": pct(matched, compared),
        "missing": len(missing),
        "unsupported": sum(1 for f in findings if f.status in BLOCKING_TRACE),
        "contradictions": sum(1 for f in findings if f.status == "Contradiction Detected"),
        "duplicates": sum(1 for f in findings if f.rule_id == "V-DUPLICATE"),
    }
