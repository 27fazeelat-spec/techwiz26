"""Check the Aurelle dataset blueprint against the SRS dataset minimums.

Usage:  python documentation/dataset/check_blueprint.py
Exit code 1 if any SRS minimum or consistency check fails.
"""
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
ROLES = {"FOA", "GRE", "HKS", "FBA", "MTT", "SEE", "RVA", "FNA", "HRE", "DMG"}
STAGES = {"D1", "W1", "W2", "D30", "D60", "D90"}
REQ_TYPES = {"Must Know", "Must Complete", "Must Demonstrate", "Must Acknowledge",
             "Recommended", "Optional", "Not Applicable"}
MANDATORY_TYPES = {"Must Know", "Must Complete", "Must Demonstrate", "Must Acknowledge"}


def load(name):
    with open(HERE / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def split(value):
    return [v for v in value.split(";") if v]


def main():
    docs = load("02_Document_Register.csv")
    reqs = load("03_Requirements_Register.csv")
    problems = []

    doc_ids = {d["doc_id"] for d in docs}
    req_ids = [r["req_id"] for r in reqs]
    req_id_set = set(req_ids)

    # ---- consistency ----
    for rid, n in Counter(req_ids).items():
        if n > 1:
            problems.append(f"duplicate req_id {rid}")
    for r in reqs:
        rid = r["req_id"]
        if r["doc_id"] not in doc_ids:
            problems.append(f"{rid}: unknown doc_id {r['doc_id']}")
        if r["req_type"] not in REQ_TYPES:
            problems.append(f"{rid}: bad req_type {r['req_type']}")
        if (r["req_type"] in MANDATORY_TYPES) != (r["mandatory"] == "Y"):
            problems.append(f"{rid}: mandatory flag disagrees with req_type")
        if r["due_stage"] and r["due_stage"] not in STAGES:
            problems.append(f"{rid}: bad due_stage {r['due_stage']}")
        roles = split(r["applies_to"])
        if roles not in (["ALL"], ["NONE"]) and not set(roles) <= ROLES:
            problems.append(f"{rid}: unknown role in {r['applies_to']}")
        for p in split(r["prerequisites"]):
            if p not in req_id_set:
                problems.append(f"{rid}: prerequisite {p} does not exist")
            if p == rid:
                problems.append(f"{rid}: is its own prerequisite")

    # ---- prerequisite cycles ----
    graph = {r["req_id"]: split(r["prerequisites"]) for r in reqs}
    state = {}

    def visit(node, path):
        if state.get(node) == "done":
            return
        if state.get(node) == "active":
            problems.append("prerequisite cycle: " + " -> ".join(path + [node]))
            return
        state[node] = "active"
        for nxt in graph.get(node, []):
            visit(nxt, path + [node])
        state[node] = "done"

    for node in graph:
        visit(node, [])

    # ---- per-role requirement sets must differ (SRS Step 16) ----
    role_sets = defaultdict(set)
    for r in reqs:
        roles = split(r["applies_to"])
        targets = ROLES if roles == ["ALL"] else set(roles) & ROLES
        for role in targets:
            role_sets[role].add(r["req_id"])
    sets = list(role_sets.items())
    for i, (a, sa) in enumerate(sets):
        for b, sb in sets[i + 1:]:
            if sa == sb:
                problems.append(f"roles {a} and {b} have identical requirement sets")

    # ---- SRS minimums ----
    all_case_refs = ";".join(r["case_refs"] for r in reqs) + ";" + ";".join(d["case_refs"] for d in docs)
    conflicts = set(re.findall(r"\bC\d{2}\b", all_case_refs))
    adversarial = set(re.findall(r"\bA\d{2}\b", all_case_refs))
    version_changes = {d["doc_id"] for d in docs if d["supersedes"]
                       and d["status"] in ("Active", "Scheduled")}
    mandatory = [r for r in reqs if r["mandatory"] == "Y"]
    role_specific = [r for r in reqs if split(r["applies_to"]) not in (["ALL"], ["NONE"])]
    used_roles = set(role_sets)

    checks = [
        ("Company documents", len(doc_ids), 20),
        ("Job roles", len(used_roles), 10),
        ("Identifiable requirements", len(reqs), 150),
        ("Mandatory requirements", len(mandatory), 50),
        ("Role-specific requirements", len(role_specific), 30),
        ("Conflicting / ambiguous cases", len(conflicts), 10),
        ("Policy version changes", len(version_changes), 10),
        ("Adversarial / injection cases", len(adversarial), 10),
    ]

    print(f"{'SRS minimum':<32}{'Required':>9}{'Actual':>9}   Result")
    print("-" * 60)
    for label, actual, minimum in checks:
        ok = actual >= minimum
        if not ok:
            problems.append(f"{label}: {actual} < {minimum}")
        print(f"{label:<32}{minimum:>9}{actual:>9}   {'PASS' if ok else 'FAIL'}")

    print(f"\nFiles incl. versions: {len(docs)}   "
          f"PDF: {sum(d['format'] == 'PDF' for d in docs)}   "
          f"DOCX: {sum(d['format'] == 'DOCX' for d in docs)}")
    print("Requirements per role:  " + "  ".join(
        f"{role} {len(role_sets[role])}" for role in sorted(role_sets)))
    print("Requirement types:      " + "  ".join(
        f"{t} {n}" for t, n in Counter(r["req_type"] for r in reqs).most_common()))

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print("  - " + p)
        sys.exit(1)
    print("\nBlueprint is consistent and meets every SRS dataset minimum.")


if __name__ == "__main__":
    main()
