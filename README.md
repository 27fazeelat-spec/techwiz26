# SkillSprint AI

**Verified onboarding, grounded in your own policies.**

SkillSprint AI turns an organisation's policies, SOPs, role descriptions and FAQs into personalised onboarding plans. Google Gemini generates the plans; an independent, deterministic Python pipeline then checks them against a human-approved Role Requirement Matrix before anything reaches an employee.

The demonstration organisation is **Aurelle Hotels & Residences**, a fictional hotel group with 12 properties in three countries, 10 job roles and 31 policy documents.

> Built for the TechWiz *Generative AI PowerPlay*.

| | |
|---|---|
| Live application | https://techwiz26-production.up.railway.app  (deployed on Railway) |
| Technical blog | https://medium.com/@27fazeelat/building-skillsprint-an-evidence-grounded-human-approved-approach-to-ai-onboarding-ad2ff2f618ed?sharedUserId=27fazeelat  |
| Evaluator instructions | [Evaluating SkillSprint](#evaluating-skillsprint) below |
| Hidden-document rehearsal | [`hidden_test_ready/`](hidden_test_ready/README.md) and [`reports/hidden_rehearsal.md`](reports/hidden_rehearsal.md) |

---

## Installation

1. **Python.** Install Python 3.12 or newer from python.org (developed and tested on 3.14). On Windows, tick *Add python.exe to PATH*.
2. **Environment.** In the project folder:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate          # Windows
   source .venv/bin/activate        # macOS / Linux
   ```
3. **Dependencies.** `python -m pip install -r requirements.txt`
4. **Configuration.** `cp .env.example .env` (Windows: `copy .env.example .env`) and fill in:
   - `SECRET_KEY`: a long random string;
   - `GEMINI_API_KEY`: a key from Google AI Studio (only needed to generate plans; everything else works without it);
   - `DATABASE_URL`: your PostgreSQL database (see [Using PostgreSQL](#using-postgresql)). Left empty, the app falls back to a local SQLite file, which is enough for a quick look.

   API keys and passwords go only in `.env` (git-ignored) or the host's secret store, never in the code or the repository.
5. **Documents.** Nothing to do locally: the 44 sample documents in `sample_documents/` are ingested on first start. For PostgreSQL, load them with the commands below.
6. **Start.** `python run.py` and open http://127.0.0.1:5000.
7. **Tests.** `python -m pytest -q` (see [Tests](#tests)).

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

1. Install PostgreSQL (version 14 or later) and create a database, for example `skillsprint`. If PostgreSQL is not installed as a service, start it with `pg_ctl start -D <data folder> -l <data folder>/server.log` before running the app.
2. In `.env`, set `DATABASE_URL=postgresql+pg8000://<user>:<password>@localhost:5432/skillsprint` and choose a `SECRET_KEY`. A plain `postgresql://` or `postgres://` URL also works; it is converted automatically. Passwords with characters such as `@` or `#` can be pasted as they are; the app encodes them. Check the connection with `python -m flask --app run db-check` (read-only).
   A database on another machine is always reached over verified TLS (certificate chain and hostname). If its certificate is not signed by a public CA, save the server's CA certificate in `config/` and set `DATABASE_SSL_ROOT_CERT` to it; `python tools/verify_ca_certificate.py <file>` checks the file against the server.
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

## Deployment

The application is deployed as a Railway web service with a PostgreSQL database.

1. Create a web service from this repository and a PostgreSQL database the service can reach.
2. Start command: `gunicorn -w 2 --threads 4 -b 0.0.0.0:$PORT run:app`
3. Variables: `SECRET_KEY`, `DATABASE_URL`, `GEMINI_API_KEY`, `GEMINI_MODEL`, and `DATABASE_SSL_ROOT_CERT` only if the database's certificate needs its own CA file. For e-mail (demo logins), either `BREVO_API_KEY`, `MAIL_FROM` and `MAIL_FROM_NAME` (HTTPS, works where SMTP is blocked, as on Railway) or `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`.
4. Run `database/postgres_hardening.sql` once, then the seed and ingest commands above against the hosted database (or restore a `pg_dump` of the local database).
5. Create the SkillSprint console login with `python -m flask --app run console-user <email>`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Cannot connect to the database at localhost:5432` | The local PostgreSQL server is not running: start it with `pg_ctl start -D <data folder>` |
| `certificate verify failed` (remote database) | Set `DATABASE_SSL_ROOT_CERT` to the server's CA file; check it with `tools/verify_ca_certificate.py` |
| Plans stay *Failed* with a Gemini error | Check `GEMINI_API_KEY` and `GEMINI_MODEL`; the error text is on the plan page and in the GenAI log |
| "The email could not be sent" | On hosts that block SMTP, set the Brevo variables instead |
| Account locked | Wait 15 minutes, or `python -m flask --app run set-password <email>` |
| Want a clean local start | Delete `instance/skillsprint.db` and start again |

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
| Contradiction detection (numbers, deadlines, frequencies, permission vs prohibition, version changes) with configurable precedence and reviewer decisions: 13 of 13 planned conflicts found | ✅ |
| Review queue: approve, reject, edit (re-validated), override with reason, regenerate one module, comment; plan assignment only after every decision | ✅ |
| Policy updates: clause-by-clause change detection, impact on items / plans / employees, regeneration of affected modules only | ✅ |
| Progress: checklist, tasks with manager sign-off, Python-scored quizzes (pass mark, attempt limit), assessments, progress status, weak areas, rule-based recommendations | ✅ |
| Job roles added at runtime (mapping preview, activation), employee profiles without sensitive data | ✅ |
| Thirteen reports from stored data (comparison, validation, traceability, hallucination, progress, …) exported as CSV, Excel and PDF | ✅ |
| Employee filters (role, department, property, verification result, progress) and plan comparison | ✅ |
| Topic check: refuses topics the approved documents do not cover (deterministic, `hallucination_checks/`) | ✅ |
| Ask the bot: employees ask questions answered only from approved passages; Python checks every citation and number, uncovered questions never reach Gemini, and the employee can send any question to their line manager | ✅ |
| Job roles dashboard: required rules, plans, coverage and onboarding progress per role | ✅ |
| Ctrl+K search across pages, documents, requirements, employees and modules | ✅ |
| Administrator settings: which pages each role sees, composable employee home, staff logins (add, change role, reset password, switch off) | ✅ |
| Public site, demo requests, SkillSprint staff console and time-limited read-only demo accounts on a separate sample workspace | ✅ |
| Hidden-document rehearsal pack (10 unseen layouts, all ingested with no special-casing) | ✅ |

## Execution instructions

Sign in as `admin@aurelle.example` (all steps) or the role named in each step.

| # | Step | Where |
|---|---|---|
| 1 | **Login** | `/login`. One page for everyone; the sidebar shows only what the role may open |
| 2 | **Upload documents** | *Documents > All documents > Upload document* (or *Upload a policy* on Home). Metadata is read from the document, the form, or inferred, and the source of each value is shown. The security scan runs on upload; findings are on *Documents > Safety check* |
| 3 | **Create role** | *Organisation > Job roles*, *Add this job*. Preview which requirements it picks up, then *Activate role* |
| 4 | **Create employee** | *Onboarding > Employees > Add employee*. Choose the job role, property, shift and line manager; the login e-mail and password are set here by an administrator |
| 5 | **Generate requirement matrix** | *Rules > All rules* to check the extracted rules, then *Rules > Who learns what > Build a new list* and *Approve this list* |
| 6 | **Generate onboarding plan** | *Onboarding > Employees*, *Make a plan* next to the employee (Gemini) |
| 7 | **Run validation** | Runs automatically after generation; the plan's *Summary* tab shows the status and scores, and *Run consistency check* repeats the outline |
| 8 | **Review comparison results** | Plan page, tab *AI vs approved list*; report *GenAI vs Python comparison* |
| 9 | **Review hallucination warnings** | Plan page, tab *Problems found* (V-HALLUCINATION, V-SOURCE) and *Things the policies do not cover*; *Rules > Is it covered?*; report *Hallucination and unsupported content* |
| 10 | **Review contradictions** | *Rules > Clashing policies* (decided by the Reviewer: `evaluator@aurelle.example`) |
| 11 | **Approve content** | Reviewer: *Decide > Approvals* (approve, reject, edit, override or regenerate, each with a reason). Then the training manager uses *Give the plan to …* on the plan page |
| 12 | **Ask a question** | Employee: *Ask a question*, or *Ask a question about this* on a module page. Try a covered question ("How much cash can my float have?"), an uncovered one, and *Ask my manager*; the manager replies on *Team questions*. Unanswered questions appear in the report *Questions the documents did not answer* |
| 13 | **Track employee progress** | Employee: `leila.haddad@aurelle.example` (*Home*, *Modules*, *Progress*). Manager: `omar.siddiqui@aurelle.example` (*My team*: sign-offs, assessments to mark, recommendations) |
| 14 | **Update policy** | Upload a new version of an existing document (for example `hidden_test_ready/documents/GDP-01_v3.0.pdf`) |
| 15 | **Regenerate affected content** | *Documents > What changed*, open the change, *Regenerate affected modules* |
| 16 | **Generate reports** | *Organisation > Reports* (training manager: *Results > Reports*): each report as CSV, Excel or PDF |

## Evaluating SkillSprint

- **Logins.** The evaluator and administrator logins for the live application are given in the submission form, not here. Locally, use the accounts in the table above.
- **Sample roles.** 10 job roles (Front Office Associate, Duty Manager, Housekeeping Supervisor, and others) with employees and managers; *Organisation > Job roles* shows each role's required rules and progress.
- **Sample documents.** `sample_documents/` (44 files, 31 documents with versions), with planted conflicts, injections, a draft and an expired SOP; the answer key is in `documentation/dataset/`.
- **Hidden documents.** Upload them on *Documents > Upload*, or run `python -m flask --app run ingest-folder <folder> --report reports/hidden_readiness.md`. The rehearsal pack in `hidden_test_ready/` shows the expected behaviour for each of the ten hidden-document types.
- **Evidence.** `reports/evidence/` holds exports of the reports from the live workspace; `reports/extraction_accuracy.md` and `reports/hidden_rehearsal.md` are generated by the tools named in them.

## Assumptions

- Documents are PDF or DOCX in English, up to 15 MB. Scanned images without a text layer are not read (no OCR).
- The approved Role Requirement Matrix is the ground truth. A person approves it; the GenAI model never decides what is mandatory.
- Precedence when documents disagree: within one document the latest effective version wins; otherwise Compliance and Policy outrank SOPs, then role descriptions, handbook, FAQ and informal guidance. A stricter lower-tier rule on life safety is kept with a warning, and same-tier disagreements go to a person (`config/precedence.yaml`). External documents never create requirements.
- Stages are Day 1, Week 1, Week 2 and the first 30, 60 and 90 days (`config/stages.yaml`). A requirement with no stage in its text gets its category's default stage, and this is shown.
- One client organisation per database. Demo visitors get a separate fictional workspace (Saffron Table Kitchens) and never see client data.
- The company, people and documents are fictional. No real personal data is used.

## Limitations

- **Generation time.** A full plan takes about 30 to 85 seconds with Gemini, mostly model time; the SRS target is 30 seconds. Regenerating one module is much faster.
- **Deterministic extraction has limits.** Recall is 99.5% and precision 100% on our register, but stage (51%), priority (67%) and exact roles (71%) are right less often (`reports/extraction_accuracy.md`). Unusual wording on hidden documents may need review.
- **Ask the bot finds passages by words, not meaning.** Everyday words are mapped to policy words in `config/bot.yaml`; a question phrased very differently from the documents may be told the documents do not cover it and can be sent to the manager. Answers are short summaries; the quoted passage is the authority.
- **Topic check matches words, not meaning.** A topic phrased with words the documents do not use (for example "kept" where the policy says "deleted") scores lower and is sent to a person rather than refused.
- **Numbers-based hallucination check.** V-HALLUCINATION compares numbers, durations and named facts with the cited source; a wrong statement with no checkable fact relies on the reviewer.
- **No OCR, no languages other than English.**
- **E-mail** needs a provider; on Railway only the Brevo HTTPS option works.

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
| `generate-plans [--roles ...]` | generate and validate one plan per job role |
| `console-user EMAIL` | create or update a SkillSprint console login |
| `restage-plans [--dry-run] [--plan CODE]` | apply the plan tidy-up rules (stages from the matrix, action-only checklists, merged duplicates) to plans stored before them; no GenAI call |

Tools (plain Python): `tools/extraction_accuracy.py`, `tools/build_hidden_pack.py`, `hidden_test_ready/rehearse.py`, `tools/build_demo_db.py`, `tools/verify_ca_certificate.py`.

## Project structure

The layout follows the SRS repository structure (§1.10.2):

```
src/                  Flask app: auth, dashboards, documents, services, CLI
document_processing/  PDF/DOCX parsers, metadata, chunker, version control
document_validation/  file and metadata checks
database/             SQLAlchemy models (PostgreSQL), audit trail, seed data
config/               YAML rules: permissions, precedence, stages, categories, Gemini settings
templates/  static/   pages; the "Terracotta & Olive" workspace theme and the public site, light + dark
security/             prompt-injection scanner
role_matrix/          deterministic requirement extraction
genai_pipeline/       Gemini client, retrieval, retry / repair / fallback
prompt_templates/  schemas/   versioned prompts and JSON schemas
python_validation/    the 17 validation rules
comparison_engine/    GenAI vs Python comparison and scores
contradiction_checks/ conflict detection and precedence
hallucination_checks/ topic support check (refuses uncovered topics)
src/bot/             Ask the bot (service in src/services/bot.py, prompt prompt_templates/ask_bot.j2)
tests/                pytest suites
sample_documents/     the Aurelle document collection (PDF + DOCX)
hidden_test_ready/    rehearsal pack for the hidden evaluation and its runner
tools/                dataset builder, accuracy tool, demo workspace and hidden pack builders
reports/              extraction accuracy, hidden rehearsal, exported evidence
screenshots/          screenshots of every main page, per role (index in screenshots/README.md)
documentation/        requirements analysis, architecture, database design, dataset blueprint
```

## Documentation

- [Requirements analysis (MoSCoW)](documentation/01_MoSCoW_Analysis.md)
- [System architecture](documentation/02_Architecture.md)
- [Database design](documentation/03_Database_Design.md)
- [Company dataset blueprint](documentation/dataset/README.md)
- [Onboarding plans for the ten job roles](reports/onboarding_plans/README.md) (export: `python tools/export_onboarding_plans.py <employee codes>`)
- [Evidence exports: comparison, validation, findings, security, GenAI runs](reports/evidence/README.md)
- [AI usage declaration](AI_USAGE.md)

## License

MIT, see [LICENSE](LICENSE). The company and documents are fictional.
