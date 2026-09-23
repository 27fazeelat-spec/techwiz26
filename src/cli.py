"""Command-line tools:  python -m flask --app run <command>

  seed              organisation, properties, roles, accounts and employee profiles (input data only)
  ingest-folder     ingest every PDF/DOCX in a folder through the normal pipeline
  refresh-versions  recompute document statuses for today's date (activates scheduled versions)
  set-password      set a user's password and clear a lockout
  detect-changes    compare document versions and record policy changes
  route-reviews     create review items for plans validated before the review queue existed
  export-reports    write every report as CSV, Excel and PDF
  generate-plans    generate and validate one plan per job role
"""
import csv
import json
import secrets
import ssl
from datetime import date
from pathlib import Path

import click
from flask import current_app
from sqlalchemy import func, select

from config.settings import today
from database import audit, db
from database.models import Document, Employee, JobRole, Organization, Property, User
from document_processing.metadata import version_key
from src.auth.models import hash_password
from src.services.ingestion import ingest_document, refresh_lineage

ROOT = Path(__file__).resolve().parents[1]
SEED_FILE = ROOT / "database" / "seed" / "aurelle_seed.json"
SAMPLE_DIR = ROOT / "sample_documents"
DEV_PASSWORD = "skillsprint-demo"


def seed_database(password=None):
    """Insert seed data if missing. Returns {email: password} for accounts created in this call."""
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    o = data["organization"]
    org = db.session.scalar(select(Organization).where(Organization.org_code == o["org_id"]))
    if org is None:
        org = Organization(org_code=o["org_id"], name=o["name"], settings=o.get("settings", {}))
        db.session.add(org)
        db.session.flush()

    properties = {p.code: p for p in db.session.scalars(select(Property).where(Property.organization_id == org.id))}
    for p in data["properties"]:
        if p["code"] not in properties:
            properties[p["code"]] = Property(organization_id=org.id, **p)
            db.session.add(properties[p["code"]])

    roles = {r.code: r for r in db.session.scalars(select(JobRole).where(JobRole.organization_id == org.id))}
    for r in data["job_roles"]:
        if r["code"] not in roles:
            roles[r["code"]] = JobRole(organization_id=org.id, status="active", **r)
            db.session.add(roles[r["code"]])
    db.session.flush()

    existing = set(db.session.scalars(select(Employee.employee_code)))
    for e in data["employees"]:
        if e["employee_id"] in existing:
            continue
        db.session.add(Employee(
            organization_id=org.id, employee_code=e["employee_id"], name=e["name"],
            job_role_id=roles[e["role_code"]].id, property_id=properties[e["property_code"]].id,
            department=e["department"], experience_level=e["experience_level"],
            experience_years=e["experience_years"], previous_experience=e["previous_experience"],
            joining_date=date.fromisoformat(e["joining_date"]), reporting_manager_code=e["reporting_manager_id"],
            certifications=e["certifications"], assignments=e["assignments"], shift_pattern=e["shift_pattern"]))

    created = {}
    emails = set(db.session.scalars(select(User.email)))
    for u in data["users"]:
        if u["email"] in emails:
            continue
        pw = password or secrets.token_urlsafe(10)
        db.session.add(User(organization_id=org.id, email=u["email"], name=u["name"], app_role=u["app_role"],
                            employee_code=u.get("employee_id"), password_hash=hash_password(pw)))
        created[u["email"]] = pw
    audit.record("system.seeded", "organization", org.org_code, detail={"accounts_created": list(created)},
                 commit=False)
    db.session.commit()
    return created


def _manifest(folder):
    path = Path(folder) / "upload_manifest.csv"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {row.pop("filename"): {k: v for k, v in row.items() if v} for row in csv.DictReader(f)}


def ingest_folder_files(folder, today_value, actor=None):
    manifest = _manifest(folder)
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in (".pdf", ".docx"))
    return [(p, ingest_document(p.read_bytes(), p.name, form=manifest.get(p.name), actor=actor, today=today_value))
            for p in files]


def bootstrap_local(app):
    """Local SQLite database only: on first start, seed data and ingest the sample documents.

    It never runs against PostgreSQL; there, use the seed and ingest-folder commands.
    """
    if db.session.scalar(select(func.count()).select_from(User)):
        return
    password = app.config.get("SEED_PASSWORD") or DEV_PASSWORD
    created = seed_database(password)
    results = ingest_folder_files(SAMPLE_DIR, today(app.config))
    print(f"[local SQLite database] seeded {len(created)} accounts (password: {password}); "
          f"ingested {sum(r.ok for _, r in results)}/{len(results)} sample documents.")


def register_cli(app):
    @app.cli.command("seed")
    def seed_command():
        """Load Aurelle organisation data and demo accounts."""
        created = seed_database(current_app.config.get("SEED_PASSWORD") or None)
        if created:
            click.echo("Accounts created (store these passwords now; they are not shown again):")
            for email, pw in created.items():
                click.echo(f"  {email:<32} {pw}")
        else:
            click.echo("Seed data already present; no accounts created.")

    @app.cli.command("ingest-folder")
    @click.argument("folder", type=click.Path(exists=True, file_okay=False))
    @click.option("--report", type=click.Path(dir_okay=False), help="Also write a readiness report (Markdown) here.")
    def ingest_folder(folder, report):
        """Ingest all PDF/DOCX files in FOLDER. Optional upload_manifest.csv supplies form fields.

        With --report, writes a per-file readiness report: how each unseen document was read, what was
        extracted, what the security scan flagged, and why anything was rejected (hidden-evaluation use).
        """
        ok = failed = 0
        lines = ["# Ingestion readiness report", "", f"Folder: `{folder}`", "",
                 "| File | Result | Document | Status | Metadata from | Chunks | Requirements | Security | Notes |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for path, result in ingest_folder_files(folder, today(current_app.config)):
            steps = {s["name"]: s["detail"] for s in result.steps}
            if result.ok:
                ok += 1
                d = result.doc
                click.echo(f"  ok      {path.name:<34} -> {d.doc_id} v{d.version} [{d.status}]")
                sources = sorted({v for v in (d.metadata_source or {}).values() if v})
                notes = "; ".join(result.warnings[:3]) + (f" (+{len(result.warnings) - 3} more)" if len(result.warnings) > 3 else "")
                lines.append(f"| {path.name} | ingested | {d.doc_id} v{d.version} | {d.status} | {', '.join(sources) or '-'} | "
                             f"{d.chunk_count} | {steps.get('Requirements', '-')} | {steps.get('Security scan', '-')} | {notes or '-'} |")
            else:
                failed += 1
                click.echo(f"  FAILED  {path.name:<34} {'; '.join(result.errors)}")
                lines.append(f"| {path.name} | **rejected** | - | - | - | - | - | - | {'; '.join(result.errors)} |")
        click.echo(f"{ok} ingested, {failed} failed.")
        if report:
            lines += ["", f"{ok} ingested, {failed} rejected. Generated by SkillSprint from the ingestion results."]
            Path(report).write_text("\n".join(lines) + "\n", encoding="utf-8")
            click.echo(f"Readiness report written to {report}")

    @app.cli.command("reprocess-documents")
    @click.option("--dry-run", is_flag=True, help="Report what would be added without writing anything.")
    def reprocess_documents(dry_run):
        """Run the security scan and requirement extraction on already-ingested documents.

        Additive and idempotent: documents that already have findings or requirements are skipped.
        Nothing is deleted; original chunk text is never modified (only the quarantine flag is set).
        """
        from database.models import Requirement, SecurityFinding
        from src.services.requirements import extract_document_requirements, link_requirements
        from src.services.security_scan import flag_irrelevant, scan_and_record
        docs = db.session.scalars(select(Document)).all()
        docs.sort(key=lambda d: (d.doc_id, version_key(d.version)))    # older versions first, for lineage
        roles = db.session.scalars(select(JobRole)).all()
        added_findings = added_reqs = 0
        for doc in docs:
            has_scan = db.session.scalar(select(func.count()).select_from(SecurityFinding)
                                         .where(SecurityFinding.document_id == doc.id)) or doc.parse.get("scanned")
            has_reqs = db.session.scalar(select(func.count()).select_from(Requirement).where(Requirement.document_id == doc.id))
            findings = [] if has_scan else scan_and_record(doc)
            if not has_scan:
                doc.parse = {**doc.parse, "scanned": True}
            db.session.flush()
            reqs = [] if has_reqs else extract_document_requirements(doc, roles)
            if not has_reqs and not has_scan:
                flag_irrelevant(doc, len(reqs))
            db.session.flush()
            added_findings += len(findings)
            added_reqs += len(reqs)
            click.echo(f"  {doc.doc_id:<10} v{doc.version:<10} +{len(findings)} findings  +{len(reqs)} requirements"
                       + ("  (already processed)" if has_scan and has_reqs else ""))
        links = link_requirements()
        if dry_run:
            db.session.rollback()
            click.echo(f"DRY RUN: would add {added_findings} findings, {added_reqs} requirements, {links} links. Nothing written.")
        else:
            audit.record("system.reprocessed", "documents", "all", detail={"findings": added_findings,
                                                                             "requirements": added_reqs}, commit=False)
            db.session.commit()
            click.echo(f"Added {added_findings} findings, {added_reqs} requirements, {links} prerequisite links.")

    @app.cli.command("upgrade-db")
    @click.option("--dry-run", is_flag=True, help="Show the changes without applying them.")
    def upgrade_db(dry_run):
        """Add columns that exist in the models but not yet in the database (additive only).

        create_all() creates missing tables but never alters existing ones. This command only adds
        new nullable columns; it never drops, renames or changes data.
        """
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        statements = []
        for table in db.Model.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue                                   # create_all() handles new tables
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable:
                    click.echo(f"  SKIPPED {table.name}.{column.name}: not nullable, needs a manual migration")
                    continue
                col_type = column.type.compile(dialect=db.engine.dialect)
                fk = next(iter(column.foreign_keys), None)
                ref = f" REFERENCES {fk.column.table.name}({fk.column.name})" if fk is not None else ""
                statements.append(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}{ref}')
        if not statements:
            click.echo("Database schema is up to date.")
            return
        for s in statements:
            click.echo(("  WOULD RUN  " if dry_run else "  RUN  ") + s)
        if not dry_run:
            with db.engine.begin() as conn:
                for s in statements:
                    conn.execute(text(s))
            audit.record("system.schema_upgraded", "database", "schema", detail={"statements": statements})
            click.echo(f"Added {len(statements)} column(s).")

    @app.cli.command("detect-conflicts")
    def detect_conflicts_command():
        """Find contradictions between current requirements and resolve them by precedence."""
        from database.models import Conflict
        from src.services.conflicts import detect_and_store
        found = detect_and_store({"email": "cli", "app_role": "system"})
        db.session.commit()
        for c in db.session.scalars(select(Conflict).where(Conflict.kind == "cross_document")):
            winner = c.winner.req_id if c.winner else "reviewer decides"
            click.echo(f"  {c.conflict_code} {c.left.doc_id} §{c.left.section_id} vs {c.right.doc_id} §{c.right.section_id}"
                       f"  [{c.rule_applied}] -> {winner}")
        click.echo(f"{len(found)} conflict(s) in total, including version changes.")

    @app.cli.command("build-matrix")
    def build_matrix_command():
        """Build a new draft Role Requirement Matrix (approve it in the web app)."""
        from src.services.matrix import build_draft
        version = build_draft({"email": "cli", "app_role": "system"})
        click.echo(f"Draft matrix v{version.version_no}: {version.stats['requirements']} requirements, "
                   f"{version.stats['rows']} rows, {version.stats['mandatory_requirements']} mandatory, "
                   f"{version.stats['role_specific_requirements']} role-specific.")
        click.echo("Per role: " + ", ".join(f"{k} {v}" for k, v in version.stats["per_role"].items()))

    @app.cli.command("route-reviews")
    def route_reviews_command():
        """Create review items for current plans validated before the review queue existed (idempotent)."""
        from database.models import Plan
        from src.services.review import latest_run, plan_review_state, route_for_review
        plans = db.session.scalars(select(Plan).where(Plan.status.notin_(["superseded", "Failed", "generating"]))).all()
        for plan in plans:
            run = latest_run(plan)
            if run is None:
                continue
            route_for_review(plan, run)
            state = plan_review_state(plan)
            click.echo(f"  {plan.plan_code} v{plan.version}: {state['open']} open, {state['decided']} decided")
        db.session.commit()
        click.echo(f"{len(plans)} plan(s) checked.")

    @app.cli.command("set-password")
    @click.argument("email")
    @click.option("--generate", is_flag=True, help="Generate a strong password and print it once.")
    def set_password_command(email, generate):
        """Set a user's password (prompted, never echoed) and clear any login lockout."""
        user = db.session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            raise click.ClickException(f"No user with email {email}.")
        if generate:
            password = secrets.token_urlsafe(12)
        else:
            password = click.prompt("New password", hide_input=True, confirmation_prompt=True)
            if len(password) < 10:
                raise click.ClickException("Use at least 10 characters.")
        user.password_hash, user.failed_logins, user.locked_until = hash_password(password), 0, None
        audit.record("user.password_set", "user", user.email, actor={"user_id": "cli", "app_role": "system"}, commit=False)
        db.session.commit()
        click.echo(f"Password set for {user.email}." + (f" New password: {password}" if generate else ""))

    @app.cli.command("export-reports")
    @click.option("--out", default="reports/generated", show_default=True, help="Folder to write the files to.")
    @click.option("--formats", default="csv,xlsx,pdf", show_default=True)
    def export_reports_command(out, formats):
        """Write every report as CSV, Excel and PDF (read-only: nothing in the database changes)."""
        from src.services import reports
        folder = ROOT / out
        folder.mkdir(parents=True, exist_ok=True)
        for name in reports.REPORTS:
            table = reports.build(name)
            for fmt in formats.split(","):
                path = folder / f"{name}.{fmt}"
                path.write_bytes(reports.FORMATS[fmt][1](table))
            click.echo(f"  {name}: {len(table.rows)} rows")
        click.echo(f"Written to {folder}")

    @app.cli.command("generate-plans")
    @click.option("--role", "roles", multiple=True, help="Role code(s); default: every active role.")
    @click.option("--pause", default=5, show_default=True, help="Seconds to wait between plans (Gemini rate limit).")
    @click.option("--regenerate", is_flag=True, help="Also generate for roles that already have a current plan.")
    def generate_plans_command(roles, pause, regenerate):
        """Generate and validate one plan per job role (the first employee in each role), one at a time."""
        import time
        from database.models import Plan
        from genai_pipeline.providers import ProviderError
        from src.services.planning import generate_plan
        query = select(JobRole).where(JobRole.status == "active").order_by(JobRole.code)
        if roles:
            query = query.where(JobRole.code.in_([r.upper() for r in roles]))
        results = []
        for n, role in enumerate(db.session.scalars(query).all()):
            employee = db.session.scalar(select(Employee).where(Employee.job_role_id == role.id)
                                         .order_by(Employee.employee_code))
            if employee is None:
                click.echo(f"  {role.code}: no employee in this role, skipped")
                continue
            current = db.session.scalar(select(Plan).where(Plan.employee_id == employee.id,
                                                           Plan.status.notin_(["superseded", "Failed"])))
            if current is not None and not regenerate:
                click.echo(f"  {role.code}: {employee.name} already has {current.plan_code} v{current.version}, skipped")
                continue
            if n and pause:
                time.sleep(pause)
            started = time.time()
            try:
                plan = generate_plan(employee, {"email": "cli", "app_role": "system"}, current_app.config)
            except (ProviderError, ValueError) as exc:
                db.session.rollback()
                click.echo(f"  {role.code}: FAILED ({exc})")
                continue
            took = time.time() - started
            results.append(plan)
            click.echo(f"  {role.code}: {employee.name:<22} {plan.plan_code} v{plan.version}  {plan.status:<24} "
                       f"coverage {plan.score_coverage}%  traceability {plan.score_traceability}%  {took:.0f} s")
        click.echo(f"{len(results)} plan(s) generated.")

    @app.cli.command("db-check")
    def db_check():
        """Read-only connection check: server, TLS verification, dataset counts. Writes nothing."""
        import os
        from urllib.parse import urlsplit
        from sqlalchemy import text
        from database.models import Chunk
        url = current_app.config["SQLALCHEMY_DATABASE_URI"]
        parts = urlsplit(url)
        click.echo(f"database : {db.engine.dialect.name} at {parts.hostname or 'local file'}"
                   + (f":{parts.port}" if parts.port else ""))
        if db.engine.dialect.name == "postgresql":
            click.echo("server   : " + db.session.execute(text("select version()")).scalar().split(",")[0])
            args = current_app.config["SQLALCHEMY_ENGINE_OPTIONS"].get("connect_args", {})
            ctx = args.get("ssl_context")
            if ctx is None:
                click.echo("TLS      : off (local server)")
            else:
                verified = ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
                ca = os.getenv("DATABASE_SSL_ROOT_CERT") or "system trust store"
                click.echo(f"TLS      : on, certificate {'VERIFIED (CA: ' + ca + ', hostname checked)' if verified else 'NOT verified'}")
        click.echo(f"documents: {db.session.scalar(select(func.count()).select_from(Document))} "
                   f"(active {db.session.scalar(select(func.count()).select_from(Document).where(Document.status == 'active'))})")
        click.echo(f"chunks   : {db.session.scalar(select(func.count()).select_from(Chunk))}")
        click.echo(f"users    : {db.session.scalar(select(func.count()).select_from(User))}")

    @app.cli.command("refresh-versions")
    def refresh_versions():
        """Recompute every lineage's statuses for today's date."""
        for doc_id in db.session.scalars(select(Document.doc_id).distinct()).all():
            for version, change in refresh_lineage(doc_id, today(current_app.config)).items():
                click.echo(f"  {doc_id} v{version}: {change['from']} -> {change['to']}")
        from database.models import ChangeImpact
        from src.services.changes import detect_changes, refresh_status
        for change in db.session.scalars(select(ChangeImpact).where(ChangeImpact.status == "upcoming")):
            refresh_status(change)
        detect_changes()
        db.session.commit()
        click.echo("Done.")

    @app.cli.command("detect-changes")
    def detect_changes_command():
        """Compare every document version with the one it replaces and record the differences (idempotent)."""
        from src.services.changes import detect_changes, impact
        for c in detect_changes(actor={"email": "cli", "app_role": "system"}):
            i = impact(c)
            click.echo(f"  {c.doc_id} v{c.from_version} -> v{c.to_version}: {c.counts} | "
                       f"{i['items']} items in {len(i['plans'])} plan(s) affected")
        db.session.commit()
        click.echo("Done.")
