# SkillSprint AI

**Verified onboarding, grounded in your own policies.**

SkillSprint AI turns an organisation's policies, SOPs, role descriptions and FAQs into personalised onboarding plans. Google Gemini generates the plans; an independent, deterministic Python pipeline then checks them against a human-approved Role Requirement Matrix before anything reaches an employee.

The demonstration organisation is **Aurelle Hotels & Residences**, a fictional hotel group with 12 properties in three countries, 10 job roles and 31 policy documents.

> Built for the TechWiz *Generative AI PowerPlay* competition (theme: OnboardVerse).

---

## Quick start (no database server needed)

```bash
python -m pip install -r requirements.txt
cp .env.example .env          # leave DATABASE_URL empty to use a local SQLite file
python run.py
```

Open http://127.0.0.1:5000. On first start with the local SQLite database (`instance/skillsprint.db`), the app seeds itself and ingests the 44 sample documents through the normal pipeline (about 20 seconds). Data persists between restarts; delete the file to start fresh. PostgreSQL is used whenever `DATABASE_URL` is set.

| Account | Role | Password (local SQLite mode) |
|---|---|---|
| `admin@aurelle.example` | Administrator | `skillsprint-demo` |
| `training@aurelle.example` | Training Manager | `skillsprint-demo` |
| `evaluator@aurelle.example` | Reviewer (evaluator login) | `skillsprint-demo` |
| `omar.siddiqui@aurelle.example` | Manager | `skillsprint-demo` |
| `leila.haddad@aurelle.example` | Employee | `skillsprint-demo` |

Set `SKILLSPRINT_TODAY=2026-09-23` in `.env` to reproduce the dataset's reference date. On that date, one policy version is scheduled for the future, one SOP has expired, and one draft is unapproved.

## Using PostgreSQL

1. Create a PostgreSQL database: locally, or on a managed service such as Render PostgreSQL, Neon or Supabase.
2. In `.env`, set `DATABASE_URL=postgresql+pg8000://<user>:<password>@<host>:5432/<database>` and choose a `SECRET_KEY`. A plain `postgres://` URL from a hosting provider also works; it is converted automatically.
   **Supabase:** use the **Session pooler** string (dashboard → *Connect* → *Session pooler*, host `aws-…pooler.supabase.com`, user `postgres.<project-ref>`). The *direct connection* host `db.<project-ref>.supabase.co` is IPv6-only and fails on IPv4 networks. Passwords with characters such as `@` or `#` can be pasted as they are; the app encodes them. TLS is always on and verified for remote databases. Supabase uses its own CA, so download it (*Project Settings* → *Database* → *SSL Configuration* → *Download certificate*), save it as `config/prod-ca-2021.crt` and set `DATABASE_SSL_ROOT_CERT=config/prod-ca-2021.crt`. Check the file with `python tools/verify_ca_certificate.py config/prod-ca-2021.crt`, and the app's connection with `python -m flask --app run db-check` (read-only).
3. Tables are created on first start. For production, run `database/postgres_hardening.sql` so the application's database role can only insert into the audit log.
4. Load data through the normal pipeline:

```bash
python -m flask --app run seed                              # organisation, roles, accounts (prints passwords once)
python -m flask --app run ingest-folder sample_documents    # parse, chunk and version all documents
python -m flask --app run refresh-versions                  # daily job: activates versions whose date has arrived
python -m flask --app run reprocess-documents --dry-run     # scan + extract documents ingested before Day 2 (additive)
python -m flask --app run detect-conflicts                  # contradictions + precedence (build-matrix also runs it)
python -m flask --app run build-matrix                      # draft Role Requirement Matrix; approve it in the web app
python -m flask --app run upgrade-db --dry-run             # add new nullable columns to an existing database
```

API keys and passwords live only in `.env` (git-ignored) or the host's secret store. They are never committed.

## Tests

```bash
python -m pytest -q
```

Tests run on in-memory SQLite. To run them against PostgreSQL, set `TEST_DATABASE_URL` to a separate, empty test database: every test drops and recreates the tables. A guard refuses to run against the app's main `DATABASE_URL` or any database that already holds real documents.

Extraction accuracy is measured against the gold register with `python tools/extraction_accuracy.py`, which writes `reports/extraction_accuracy.md`.

The suite ingests the full sample collection and checks the results against the dataset's answer key. For example, every one of the 185 register requirements has to be traceable to a chunk with the correct document version and section.

## What works so far

| Area | Status |
|---|---|
| Login, five user roles, permission checks on every route, account lockout, CSRF | ✅ |
| Upload with file-type detection from content, size, duplicate and empty checks | ✅ |
| PDF parsing (page numbers, headings, tables, footers, watermark removal, hidden white text) | ✅ |
| DOCX parsing (heading styles, tables, footers, hidden runs, file properties) | ✅ |
| Metadata from document header → upload form → inferred, with the source shown per field | ✅ |
| Section-aware chunking with document, version, section, heading path and location | ✅ |
| Version control: active / superseded / scheduled / expired / draft | ✅ |
| PostgreSQL schema (SQLAlchemy), original files stored in the database, append-only audit log | ✅ |
| Audit trail, admin overview, document list and detail pages | ✅ |
| Prompt-injection scanner: 12 techniques, quarantine, hidden text excluded (all 12 planted cases caught, no false alarms) | ✅ |
| Deterministic requirement extraction with lineage across versions (recall 99.5%, precision 100% vs the gold register) | ✅ |
| Role Requirement Matrix: draft build, human review of requirements (audited), approval | ✅ |
| Gemini generation: sharded Phase-1 outline, deterministic modules, parallel module content, retry / repair / fallback, every call logged | ✅ |
| Python validation: 17 rules (coverage, role, condition, stage, sequence, sources, quiz answers, numeric-fact hallucination check, duplicates, rubric) | ✅ |
| GenAI vs Python comparison, item and plan statuses, coverage / traceability / consistency scores, plan page with traceability | ✅ |
| Contradiction detection (numbers, deadlines, frequencies, permission vs prohibition, version changes) with configurable precedence and reviewer decisions: 12 of 12 planned conflicts found | ✅ |
| Review queue: approve, reject, edit (re-validated), override with reason, regenerate one module, comment; plan assignment only after every decision | ✅ |
| Policy updates: clause-by-clause change detection, impact on items / plans / employees, regeneration of affected modules only | ✅ |
| Progress: checklist, tasks with manager sign-off, Python-scored quizzes (pass mark, attempt limit), assessments, progress status, weak areas, rule-based recommendations | ✅ |
| Job roles added at runtime (mapping preview, activation), employee profiles without sensitive data | ✅ |
| Twelve reports from stored data (comparison, validation, traceability, hallucination, progress, …) exported as CSV, Excel and PDF | ✅ |
| Employee filters (role, department, property, verification result, progress) and plan comparison | ✅ |

## Commands

All run as `python -m flask --app run <command>`:

| Command | What it does |
|---|---|
| `seed` | organisation, properties, roles, accounts and employee profiles |
| `ingest-folder PATH [--report FILE]` | ingest every PDF/DOCX in a folder; `--report` writes a per-file readiness report |
| `build-matrix` / `detect-conflicts` / `detect-changes` | rebuild the matrix draft, the conflicts, the policy changes |
| `route-reviews` | create review items for plans validated before the review queue existed |
| `export-reports [--out DIR]` | write every report as CSV, Excel and PDF |
| `set-password EMAIL [--generate]` | set a password and clear a lockout |
| `db-check` / `upgrade-db --dry-run` | read-only connection check; list additive schema changes |

## Project structure

The layout follows the SRS repository structure (§1.10.2):

```
src/                  Flask app: auth, dashboards, documents, services, CLI
document_processing/  PDF/DOCX parsers, metadata, chunker, version control
document_validation/  file and metadata checks
database/             SQLAlchemy models (PostgreSQL), audit trail, seed data
config/               YAML rules: permissions, precedence, stages, categories, Gemini settings
templates/  static/   pages and the "Clean Verified" design tokens (light + dark)
tests/                pytest suites
sample_documents/     the Aurelle document collection (PDF + DOCX)
tools/dataset_builder generator and verifier for the sample documents
documentation/        requirements analysis, architecture, database design, dataset blueprint
```

## Documentation

- [Requirements analysis (MoSCoW)](documentation/01_MoSCoW_Analysis.md)
- [System architecture](documentation/02_Architecture.md)
- [Database design](documentation/03_Database_Design.md)
- [Company dataset blueprint](documentation/dataset/README.md)
- [AI usage declaration](AI_USAGE.md)
