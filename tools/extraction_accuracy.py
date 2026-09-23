"""Measure requirement extraction against the dataset's gold register.

Development and test tool only: the application never reads documentation/dataset/.

    python tools/extraction_accuracy.py          # ingest samples into a temporary database and report

Matching: an extracted requirement matches a gold requirement when both come from the same document
version and one clause text contains the other (after whitespace normalisation).
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATASET = ROOT / "documentation" / "dataset"
ALL_ROLES = ["FOA", "GRE", "HKS", "FBA", "MTT", "SEE", "RVA", "FNA", "HRE", "DMG"]


def _norm(text):
    return " ".join((text or "").replace("​", "").split()).lower()


def _roles(value):
    codes = value if isinstance(value, list) else [c for c in value.split(";") if c]
    return set(ALL_ROLES) if codes == ["ALL"] else set(codes)


def _read(name):
    with open(DATASET / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def evaluate(session):
    from sqlalchemy import select
    from database.models import Requirement

    docs = _read("02_Document_Register.csv")
    register_version, tier0 = {}, {d["doc_id"] for d in docs if d["tier"] == "0"}
    for d in docs:
        if d["status"] in ("Active", "Expired"):
            register_version.setdefault(d["doc_id"], d["version"])
    gold = [g for g in _read("03_Requirements_Register.csv")
            if g["req_type"] != "Not Applicable" and g["doc_id"] not in tier0]
    extracted = [r for r in session.scalars(select(Requirement)).all()
                 if register_version.get(r.doc_id) == r.version]

    pairs, used = [], set()
    for g in gold:
        gt = _norm(g["clause_text"])
        match = next((r for r in extracted if r.id not in used and r.doc_id == g["doc_id"]
                      and (gt in _norm(r.text) or _norm(r.text) in gt)), None)
        if match is not None:
            used.add(match.id)
            pairs.append((g, match))
    missed = [g for g in gold if g not in [p[0] for p in pairs]]
    extra = [r for r in extracted if r.id not in used]

    def share(check):
        return sum(1 for g, r in pairs if check(g, r)) / len(pairs) if pairs else 0.0

    jaccard = [len(_roles(g["applies_to"]) & set(_roles(r.roles))) / len(_roles(g["applies_to"]) | set(_roles(r.roles)))
               for g, r in pairs]
    gold_cond = [(g, r) for g, r in pairs if g["condition"]]
    return {
        "gold": len(gold), "extracted": len(extracted), "matched": len(pairs),
        "recall": len(pairs) / len(gold) if gold else 0.0,
        "precision": len(pairs) / len(extracted) if extracted else 0.0,
        "mandatory_accuracy": share(lambda g, r: (g["mandatory"] == "Y") == r.mandatory),
        "type_accuracy": share(lambda g, r: g["req_type"] == r.req_type),
        "section_accuracy": share(lambda g, r: g["section"] == r.section_id),
        "stage_accuracy": share(lambda g, r: g["due_stage"] == r.due_stage),
        "priority_accuracy": share(lambda g, r: g["priority"] == r.priority),
        "competency_accuracy": share(lambda g, r: g["competency"] == r.competency),
        "roles_exact": share(lambda g, r: _roles(g["applies_to"]) == set(_roles(r.roles))),
        "roles_jaccard": sum(jaccard) / len(jaccard) if jaccard else 0.0,
        "condition_recall": (sum(1 for g, r in gold_cond if r.condition) / len(gold_cond)) if gold_cond else 0.0,
        "condition_false": sum(1 for g, r in pairs if r.condition and not g["condition"]),
        "missed": [(g["req_id"], g["doc_id"], g["section"], g["clause_text"]) for g in missed],
        "extra": [(r.req_id, r.section_id, r.text) for r in extra],
    }


def format_report(m):
    lines = ["# Requirement extraction accuracy", "",
             "Measured against the gold register in `documentation/dataset/03_Requirements_Register.csv` "
             "(external and 'Not Applicable' items excluded).", "",
             "| Measure | Result |", "|---|---|",
             f"| Gold requirements | {m['gold']} |", f"| Extracted (register versions) | {m['extracted']} |",
             f"| Matched | {m['matched']} |",
             f"| **Recall** | **{m['recall']:.1%}** |", f"| **Precision** | **{m['precision']:.1%}** |"]
    for key, label in [("mandatory_accuracy", "Mandatory / optional correct"), ("type_accuracy", "Requirement type correct"),
                       ("section_accuracy", "Section ID correct"), ("stage_accuracy", "Due stage correct"),
                       ("priority_accuracy", "Priority correct"), ("competency_accuracy", "Competency correct"),
                       ("roles_exact", "Roles exactly right"), ("roles_jaccard", "Roles overlap (mean Jaccard)"),
                       ("condition_recall", "Conditions detected (of gold conditional)")]:
        lines.append(f"| {label} | {m[key]:.1%} |")
    lines.append(f"| Conditions wrongly added | {m['condition_false']} |")
    lines += ["", f"## Missed ({len(m['missed'])})", ""] + [f"- `{a}` {b} §{c}: {d}" for a, b, c, d in m["missed"]]
    lines += ["", f"## Extracted but not in the register ({len(m['extra'])})", ""] + \
             [f"- `{a}` §{b}: {c}" for a, b, c in m["extra"]]
    return "\n".join(lines) + "\n"


def main():
    import os
    os.environ.pop("DATABASE_URL", None)
    from datetime import date
    from src import create_app
    from database import db
    from src.cli import ingest_folder_files, seed_database
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://", "TODAY_OVERRIDE": "2026-09-23"})
    with app.app_context():
        seed_database(password="report-only")
        ingest_folder_files(ROOT / "sample_documents", date(2026, 9, 23))
        report = format_report(evaluate(db.session))
    out = ROOT / "reports" / "extraction_accuracy.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"Written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
