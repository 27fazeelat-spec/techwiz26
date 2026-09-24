"""Hidden-evaluation rehearsal: ingest the pack into a throw-away local database and report what happened.

    python tools/build_hidden_pack.py          # (re)build the ten documents
    python hidden_test_ready/rehearse.py       # writes reports/hidden_rehearsal.md

It never touches the hosted database: DATABASE_URL is cleared and a new SQLite file is created in the temp
folder, loaded with the Aurelle sample documents (the baseline), and deleted afterwards. No GenAI call is made.
The same folder can be ingested into a real workspace with:

    python -m flask --app run ingest-folder hidden_test_ready/documents --report reports/hidden_readiness.md
"""
import os
import secrets
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["DATABASE_URL"] = ""                                    # never the hosted database
PACK = ROOT / "hidden_test_ready" / "documents"
OUT = ROOT / "reports" / "hidden_rehearsal.md"
ACTOR = {"user_id": "rehearsal", "email": "rehearsal", "app_role": "system"}

EXPECTED = {
    "VAL-01": ("H01", "New company policy", "Ingested as active; new requirements for Front Office Associates and Duty Managers"),
    "GDP-01": ("H02", "Revised existing policy", "v3 replaces v2; the change record shows the 7 to 3 day retention change and one added consent rule"),
    "ROL-04": ("H03", "New job role", "Once the Night Auditor role is added on the Job roles page, existing night audit and cash rules map to it"),
    "FAQ-02": ("H04", "Conflicting FAQ", "Its single-person count conflicts with the two-person float count in PCH-01; the policy wins"),
    "SOP-FO-02": ("H05", "Outdated SOP", "Recognised as older than the active v1.2: filed as superseded, never active"),
    "LPP-01": ("H06", "Missing / incomplete requirement", "The reference to Annex B is recorded as unresolved"),
    "PLS-01": ("H07", "Prompt-injection document", "The instruction in the DOCX file properties is recorded as a high-severity finding and never reaches a prompt"),
    "CMP-02": ("H08", "New compliance requirement", "A mandatory Week 1 rule for all employees; it enters every role in the next matrix"),
    "SOP-FO-03": ("H09", "Role-specific exception", "A permission that applies to Front Office Associates, with its condition kept"),
    "TRN-01": ("H10", "Ambiguous clause", "Weak wording and no stage: extracted as a recommendation with a default stage, for review"),
}


def main():
    work = Path(tempfile.mkdtemp(prefix="skillsprint-rehearsal-"))
    db_file = work / "rehearsal.db"
    from src import create_app
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///" + db_file.as_posix(), "SKIP_LOCAL_BOOTSTRAP": True})
    with app.app_context():
        from sqlalchemy import select
        from config.settings import today
        from database import db
        from database.models import ChangeImpact, Conflict, JobRole, Organization, Requirement, SecurityFinding
        from src.cli import SAMPLE_DIR, ingest_folder_files, seed_database
        from src.services import matrix
        from src.services.changes import detect_changes
        db.create_all()
        run_date = today(app.config)

        seed_database(password=secrets.token_urlsafe(16))                 # baseline: the Aurelle sample workspace
        base = ingest_folder_files(SAMPLE_DIR, run_date, actor=ACTOR)
        detect_changes(actor=ACTOR)
        baseline = matrix.build_draft(ACTOR)
        matrix.approve(baseline.version_no, ACTOR)
        db.session.commit()
        known_conflicts = set(db.session.scalars(select(Conflict.pair_key)))
        print(f"baseline: {sum(r.ok for _, r in base)}/{len(base)} sample documents, matrix v{baseline.version_no}")

        started = time.perf_counter()
        org = db.session.scalar(select(Organization))                    # H03: the admin adds the new role first
        db.session.add(JobRole(organization_id=org.id, code="NAU", name="Night Auditor", department="Front Office",
                               aliases=["Night Auditor", "Night Auditors"], status="active"))
        db.session.commit()
        results = ingest_folder_files(PACK, run_date, actor=ACTOR)
        detect_changes(actor=ACTOR)
        draft = matrix.build_draft(ACTOR)
        db.session.commit()
        seconds = time.perf_counter() - started

        new_conflicts = [c for c in db.session.scalars(select(Conflict)) if c.pair_key not in known_conflicts]
        req_by_id = {r.id: r for r in db.session.scalars(select(Requirement))}
        rows = []
        for path, result in results:
            doc = result.doc
            doc_id = doc.doc_id if doc else path.stem.split("_v")[0]
            case, kind, expected = EXPECTED.get(doc_id, ("-", "-", "-"))
            if not result.ok:
                rows.append((case, kind, path.name, "rejected: " + "; ".join(result.errors), expected))
                continue
            reqs = [r for r in req_by_id.values() if r.document_id == doc.id]
            seen = [f"status **{doc.status}**", f"{len(reqs)} requirement(s)"]
            if reqs:
                types = sorted({r.req_type for r in reqs})
                roles = sorted({role for r in reqs for role in (r.roles or [])})
                seen.append(f"types {', '.join(types)}; roles {', '.join(roles) or 'none matched'}")
                defaults = [r for r in reqs if r.stage_source == "default"]
                if defaults:
                    seen.append(f"{len(defaults)} with no stage in the text (default stage used)")
                unresolved = [ref["text"] for r in reqs for ref in (r.cross_refs or []) if ref.get("resolved") is False]
                if unresolved:
                    seen.append("unresolved reference: " + ", ".join(sorted(set(unresolved))))
            findings = db.session.scalars(select(SecurityFinding).where(SecurityFinding.document_id == doc.id)).all()
            if findings:
                seen.append("security: " + ", ".join(sorted({f"{f.technique} ({f.severity})" for f in findings})))
            mine = {r.id for r in reqs}
            clashes = [c for c in new_conflicts if {c.left_requirement_id, c.right_requirement_id} & mine]
            for c in clashes[:2]:
                other = req_by_id[c.right_requirement_id if c.left_requirement_id in mine else c.left_requirement_id]
                seen.append(f"conflict {c.conflict_code} with {other.req_id} ({c.status.replace('_', ' ')})")
            change = db.session.scalar(select(ChangeImpact).where(ChangeImpact.to_document_id == doc.id))
            if change:
                counts = ", ".join(f"{k} {v}" for k, v in change.counts.items() if v)
                seen.append(f"change v{change.from_version} to v{change.to_version}: {counts}")
            rows.append((case, kind, path.name, "; ".join(seen), expected))

        per_role = draft.stats.get("per_role", {})
        before = baseline.stats.get("per_role", {})
        role_lines = [f"| {code} | {before.get(code, 0)} | {n} |" for code, n in sorted(per_role.items())]

    lines = ["# Hidden-evaluation rehearsal", "",
             f"Run on {date.today().isoformat()} against a throw-away local database (baseline: the Aurelle sample "
             f"documents). Ingesting the pack, detecting changes and conflicts, and building the new draft matrix took "
             f"**{seconds:.1f} s**. The pack goes through the same code and configuration as the sample documents; nothing is special-cased.", "",
             "Rebuild with `python tools/build_hidden_pack.py` and `python hidden_test_ready/rehearse.py`.", "",
             "| Case | SRS hidden item | File | What SkillSprint did | Expected |", "|---|---|---|---|---|"]
    lines += [f"| {a} | {b} | `{c}` | {d} | {e} |" for a, b, c, d, e in sorted(rows)]
    lines += ["", "## Requirements per role, approved matrix before and draft matrix after", "",
              "| Role | Before | After |", "|---|---|---|"] + role_lines
    lines += ["", "Compare the two columns in *What SkillSprint did* and *Expected*; a difference is a finding to fix, "
                  "not something to hide.", ""]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    try:
        db_file.unlink()
        work.rmdir()
    except OSError:
        pass
    print(f"{len(rows)} files in {seconds:.1f} s; report written to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
