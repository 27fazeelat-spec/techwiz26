"""Build the sample workspace that demo visitors see: "Saffron Table Kitchens", a made-up restaurant group.

It runs the real pipeline on a separate SQLite file, so the sample looks and behaves like a client workspace but
holds no client's data:

    python tools/build_demo_db.py            # writes database/demo/saffron_demo.db (uses Gemini for 2 plans)

Steps: seed the company, ingest the documents in database/demo/documents, detect conflicts, build and approve the
matrix, generate two plans, approve one plan's review items and assign it, record some progress for its employee,
and record the policy change between the two allergen SOP versions. The app copies this file at start-up and
opens it for demo visitors only (database/demo_db.py).
"""
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["DATABASE_URL"] = ""                                   # never the hosted database
DEMO = ROOT / "database" / "demo"
OUT = DEMO / "saffron_demo.db"
TODAY = "2026-09-24"
ACTOR = {"user_id": "demo-builder", "email": "demo-builder", "app_role": "system"}


def main():
    if OUT.exists():
        OUT.unlink()
    from src import create_app
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(OUT).replace("\\", "/"), "TODAY_OVERRIDE": TODAY,
                      "SKIP_LOCAL_BOOTSTRAP": True})           # the local auto-setup would load a client's documents
    with app.app_context():
        from datetime import date
        from sqlalchemy import select
        from database import db
        from database.models import Employee, Plan, Progress, ReviewItem
        from src.cli import ingest_folder_files, seed_database
        from src.services import changes, conflicts, matrix, planning, review
        db.create_all()
        seed_database(password=secrets.token_urlsafe(16), seed_file=DEMO / "saffron_seed.json")
        results = ingest_folder_files(DEMO / "documents", date.fromisoformat(TODAY), actor=ACTOR)
        print("documents:", ", ".join(f"{p.name} {'ok' if r.ok else 'FAILED'}" for p, r in results))
        conflicts.detect_and_store(ACTOR)
        db.session.commit()
        version = matrix.build_draft(ACTOR)
        matrix.approve(version.version_no, ACTOR)
        print(f"matrix v{version.version_no}: {version.stats['requirements']} requirements, per role {version.stats['per_role']}")

        plans = {}
        for code in ("S001", "S002"):
            employee = db.session.scalar(select(Employee).where(Employee.employee_code == code))
            plan = planning.generate_plan(employee, ACTOR, app.config)
            plans[code] = plan
            print(f"plan {plan.plan_code}: {plan.status}, coverage {plan.score_coverage}%" + (f" ({plan.error})" if plan.error else ""))

        maya = plans["S001"]
        if maya.status != "Failed":                               # Maya's plan: reviewed and assigned, with progress
            items = db.session.scalars(select(ReviewItem).where(ReviewItem.plan_id == maya.id, ReviewItem.status == "open")).all()
            for kind in {r.original_status for r in items}:
                group = [r for r in items if r.original_status == kind]
                review.decide_many(group, "approve", ACTOR, review.BULK_REASONS.get(kind, review.BULK_REASONS["Manual Review Required"]))
            review.assign_plan(maya, ACTOR)
            rows = db.session.scalars(select(Progress).where(Progress.plan_id == maya.id).order_by(Progress.due_date, Progress.id)).all()
            from datetime import datetime
            done = 0
            for r in rows:
                if r.plan_item.item_type in ("checklist", "quiz_question") and done < max(4, len(rows) // 3):
                    r.status, r.completed_at = "completed", datetime(2026, 9, 22, 10)
                    if r.plan_item.item_type == "quiz_question":
                        r.score = 100
                    done += 1
            db.session.commit()
            print(f"Maya: {done} of {len(rows)} steps marked done")
        # Tomas's plan stays in the review queue, so the reviewer pages have something to show.
        changes.detect_changes(actor=ACTOR)
        db.session.commit()

        # Guard: the sample must hold nothing but the sample company and its own documents.
        from database.models import Document, Organization, User
        orgs = db.session.scalars(select(Organization.name)).all()
        docs = set(db.session.scalars(select(Document.doc_id)))
        allowed = {p.name.split("_v")[0] for p in (DEMO / "documents").glob("*_v*.*")}
        users = db.session.scalars(select(User.email)).all()
        assert orgs == ["Saffron Table Kitchens"], orgs
        assert docs <= allowed, docs - allowed
        assert all(e.endswith("@saffrontable.example") for e in users), users
        print("guard: one sample company,", len(docs), "sample documents,", len(users), "sample user(s)")
    print(f"written {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
