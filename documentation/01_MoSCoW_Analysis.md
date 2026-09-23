# SkillSprint AI — Requirements Analysis & MoSCoW Prioritization

**Source:** SkillSprint AI SRS v1.0 (Aptech, "OnboardVerse" theme, Generative AI PowerPlay)
**Stack:** Python · Flask · PostgreSQL · HTML/CSS/JS
**Scope of this document:** every functional requirement (FR i–lxvi), every development step (Steps 1–63), the non-functional requirements (NFR 1–5), the competition integrity rules (§1.8) and the deliverables (§1.10).

---

## 1. Executive Summary

### What the SRS actually is

On the surface SkillSprint AI looks like an onboarding LMS. Read closely, though, most of the SRS is about **trust in GenAI output**. Of the 66 functional requirements, roughly 30 deal with validation, traceability, detection, review or audit, and only about 12 deal with generating content. The evaluation challenges in §1.8 (hidden documents, hidden role, policy update, injection, contradiction, traceability, hallucination, live code change, deliberate defect) test **the verification layer**, not the look of the learning content.

In one sentence, the product is:

> An onboarding generator where GenAI writes the content, and a deterministic Python engine decides whether that content is allowed to reach an employee.

Everything in this analysis follows from that.

### The one rule that governs prioritization

The SRS says (end of §1.7): *"It is a must to implement the FUNCTIONAL and NON-FUNCTIONAL requirements given in this SRS."* So, being honest about it:

- **Every FR i–lxvi is mandatory for grading.** MoSCoW here does **not** mean "skip the Should Haves". It means **build order and depth**: Must Have gets built first and deep; Should Have gets built after the core works and can be lighter.
- **Won't Have** holds only what the SRS itself puts out of scope (§1.4) or what it never asks for.
- **Could Have** holds only what the SRS marks optional (e.g. TXT/MD/CSV) plus a small number of additions that directly strengthen an evaluated challenge.

### Five design decisions the SRS forces (and that most teams will get wrong)

1. **The Role Requirement Matrix cannot come from the GenAI model.** It is the ground truth that Pipeline 2 checks Pipeline 1 against. If an LLM builds it, the validation is circular: the AI grades the AI. The matrix must be produced by **deterministic Python extraction** (clause parsing, modal-verb classification, document metadata) and then **approved by a human admin**. That approval is what makes it an "approved" matrix.
2. **GenAI must never hold authority.** Verification status, coverage, traceability, precedence and approval are all computed by Python. This is also the strongest defence against prompt injection: even if a document tricks the model into writing "approve this employee", there is no field in the schema through which that text can approve anything.
3. **Everything evaluators may change live must be config, not code.** Stages, precedence order, validation rules, quiz types, JSON schema, mandatory flags and onboarding duration all belong in `config/` (YAML) and `schemas/`. Live Code Modification (§1.8.9) then becomes a two-minute edit instead of a panic.
4. **Hidden documents will not follow our formatting conventions.** Our own dataset can carry a clean metadata header, but ingestion must still work when that header is missing. That means an upload form with metadata fields, heuristic heading detection, and date/version extraction from the text, with anything uncertain flagged instead of guessed.
5. **Hallucination detection must be deterministic.** We check source-ID validity, lexical/semantic similarity between each generated claim and its cited chunk, and whether every number, duration and named entity in the generated text appears in the source. No "ask the LLM whether it hallucinated".

### Honest risk assessment

| Risk | Why it matters | Mitigation |
|---|---|---|
| Dataset creation is large (20 docs, 150+ reqs, 50 mandatory, 10 conflicts, 10 version changes, 10 injections) | Nothing works or can be demoed without it; hidden evaluation is judged against it | Start on Day 1 in parallel with the code; one owner; write the requirement list in a spreadsheet first, then the documents |
| 30-second generate + validate target (NFR 1) | A full plan with modules, quizzes and rubrics in one LLM call can exceed 30s | Generate per stage in parallel; keep the consistency re-run off the critical path (async/on demand) |
| API quota / rate limits | Consistency testing doubles the calls; the demo can die on a 429 | Provider adapter, backoff retry, response caching keyed by (prompt version + source hash) that is never presented as a fresh generation |
| "No hard-coded output" rule (§1.8.12) | Seeded demo plans could look like fakes | Everything in the DB must be traceable to a logged generation run with its prompt version and raw response |
| Deliverables load (report with 4 UML diagrams, 2,000-word blog, video, 100-row comparison report, security report) | Easily a full day of work | Generate evidence reports from the app itself; write docs continuously |
| Free-tier hosting sleeps | Violates the 99% uptime NFR during evaluation | Paid starter tier or keep-alive during the evaluation window; managed PostgreSQL |

### Two SRS inconsistencies to resolve explicitly (and document)

- **Two different status lists.** §1.2 lists 9 statuses (Verified, Verified with Warning, Partially Verified, Source Support Missing, Requirement Missing, Unsupported Requirement, Outdated Source, Contradiction Detected, Manual Review Required). Step 47 lists 6 (Verified, Verified with Warning, Incomplete, Unsupported, Contradictory, Manual Review Required). **Resolution:** the §1.2 list becomes **item-level** statuses (per requirement or per generated item) and Step 47 becomes the **plan-level** final status, derived from item statuses by a documented rule. This satisfies both lists and reads as deliberate engineering.
- **"Table 1: Role Requirement Matrix"** is really a GenAI-vs-Python comparison table, not the matrix. We implement both: the matrix (Step 10 fields) and the comparison (Step 46 fields).

---

## 2. MoSCoW Prioritization Table

Legend: **M** = Must, **S** = Should, **C** = Could, **W** = Won't.
"Evaluated in" shows where evaluators will look: **V** = demo video list, **Ch** = §1.8 challenge, **D** = submission deliverable.

### MUST HAVE — the system does not exist without these

| Area | Requirements | FR / Step | Evaluated in |
|---|---|---|---|
| **Access** | Secure login, RBAC (Admin, Training Manager, Reviewer, Manager, Employee) | FR i, ii | V, D (unauthorized-access tests) |
| **Company dataset** | Fictional company, 20+ docs, 10+ roles, 150+ reqs, 50+ mandatory, 30+ role-specific, 10+ conflicts, 10+ version changes, 10+ injection cases | Steps 1–3, Hint | D, Ch 1 |
| **Ingestion** | PDF + DOCX upload; validation (type, size, duplicate by hash, empty, version, effective/expiry date, department, category); parsing with page (PDF) / paragraph (DOCX) refs; traceable chunking; source metadata | FR v–ix, Steps 4–7 | V, Ch 2, D |
| **Versioning** | Active vs superseded vs expired; `supersedes` link | FR x, Step 8 | Ch 4, Ch 6 |
| **Ground truth** | Deterministic requirement extraction (Must Know / Complete / Demonstrate / Acknowledge / Recommended / Optional / N/A; mandatory vs informational); Role Requirement Matrix with all Step 10 fields; admin approval of the matrix | FR xi, xii, Steps 10–11 | V, Ch 3, D |
| **Roles & employees** | Role CRUD incl. adding a new role at runtime; employee profile (no sensitive PII) | FR iii, iv, Step 9 | V, Ch 3 |
| **Pipeline 1 (GenAI)** | Provider integration; versioned prompt templates in files; structured JSON output; generation of plan, stages, modules, objectives, checklists, tasks, quizzes (MCQ, multi-response, T/F, scenario), assessments + rubrics; source citation on every item | FR xiii–xxii, xxiv, xxvi, xxvii, xxx, Steps 12–18, 20–21, 23–24, 37, 40 | V, D |
| **Schema & resilience** | Pydantic/JSON-Schema validation (missing fields, types, invalid source IDs, invalid role, duplicate IDs, missing mandatory flag); bounded retry with logging; timeout/quota/invalid-response handling | FR xvi, lxiii, lxiv, Steps 38–39 | D (failure examples, retry evidence), Ch 10 |
| **Run metadata** | Prompt version, model, timestamp, source-doc versions on every plan | FR lxv, Step 41 | D, Ch 7 |
| **Pipeline 2 (Python validation)** | Independent engine: mandatory coverage, requirement/source/section ID validity, mandatory flag match, competency, missing, unsupported, duplicates, outdated references, checklist completeness, task-role alignment, assessment-topic coverage, quiz-source mapping, quiz answer validation, sequencing, prerequisites, business rules | FR xxv, xxviii, xxix, xxxi, xxxii, xxxviii, xxxix, Steps 22, 26–28, 35–36 | V, D, Ch 10 |
| **Scores** | Coverage score (exact SRS formula), traceability score, consistency score, missing / unsupported / contradiction counts | FR xxxiii, xxxiv, xli, §1.2 | V, D |
| **Detection** | Hallucination detection; unsupported-content classification (supported / instructional wording / unsupported claim); contradiction detection (old vs new, FAQ vs policy, role desc vs SOP, task vs rule); configurable policy precedence | FR xxxv–xxxvii, Steps 31–34 | V, Ch 6, Ch 8, D |
| **Comparison & status** | GenAI vs Python field-level comparison; item-level + plan-level verification status; "Verified" only when 100% mandatory coverage + valid sources + no unresolved contradictions or unsupported items | FR xlii, xliii, Steps 46–47 | V, D (100-row report) |
| **Consistency** | Repeated controlled generation compared on structured sets (mandatory reqs, sources, module categories, assessment topics) | FR xl, xli, Steps 44–45 | D |
| **Human control** | Manual review queue; approve / reject / edit / regenerate / comment; reviewer override; immutable audit trail with original + override | FR xliv–xlvii, Steps 48–49 | V, D |
| **Security** | Documents treated as data; injection scanner at ingestion; adversarial content flagged and quarantined; no GenAI authority over decisions; API keys in env only | FR xlviii, xlix, Steps 42–43 | V, Ch 5, D (security report) |
| **Change management** | Policy update detection; impact analysis (modules, checklist items, tasks, quiz questions, employees, plans); selective regeneration of affected modules only | FR lvii–lix, Steps 57–59 | V, Ch 4 |
| **Core UI** | Employee dashboard; admin dashboard; progress tracking (module, checklist, task, quiz, assessment, overall); responsive interface | FR l, li, liii, lxvi, Steps 50–51, 53 | V |
| **Minimum reporting** | GenAI/Python comparison report (≥100 rows) and validation report, exportable as CSV | FR lxi, lxii (partial), §1.10.6, 1.10.8 | V, D |

### SHOULD HAVE — required by the SRS, built once the core works

| Area | Requirements | FR / Step | Why not Must-first |
|---|---|---|---|
| Scenario generation (full) | Scenario objects built from process requirements (complaint, escalation, violation, infosec, workflow issue) | FR xxiii, Step 19 | Uses the same generation and validation path as tasks; a minimal version ships with tasks in Must, and the richer scenario UI comes later |
| Difficulty levels | Beginner / Intermediate / Advanced driven by role + experience level | Step 25 | A single field plus a prompt parameter; cheap once generation is stable |
| Distractor validation (depth) | Distractors must not be true per source and must not contradict it misleadingly | Step 22 | The answer-vs-source check is Must; checking distractors is a refinement |
| Role dashboard | Requirements + completion statistics per role | FR lii, Step 52 | Aggregations over data that already exists |
| Progress assessment | On Track / Requires Attention / Behind Schedule / Assessment Required / Completed | FR liv, Step 54 | Rule over progress + due stages; needs progress data first |
| Weak-area detection | From quiz scores, assessment results, incomplete tasks, repeated errors | FR lv, Step 56 | Needs quiz attempts to exist |
| Adaptive recommendations | Revision module / extra quiz / extra task / advanced module / manager review | FR lvi, Step 55 | Depends on weak-area detection; rule-based mapping |
| Search & filtering | Employee, role, department, module, policy, status, progress, verification result | FR lx, Step 61 | Build one reusable filter component; also needed for "add a dashboard filter" (Ch 9) |
| Full reports | Employee progress, role coverage, mandatory training, assessment results, traceability, hallucination flags, policy coverage | FR lxi, Step 62 | Mostly queries + templates once data exists |
| PDF + Excel export | In addition to CSV | FR lxii, Step 63 | Libraries do the heavy lifting |
| Training plan comparison | Across roles, departments, levels, document versions | Step 60 | Listed as a Step but not in FR i–lxvi; still expected |
| Performance target | ≤30s generate + validate | NFR 1 | Tune after correctness |
| Scalability readiness | 1,000 employees / 100 roles / 1,000 docs | NFR 2 | PostgreSQL indexes + pagination; design for it from the start, verify late |
| Availability | 99% uptime during evaluation | NFR 5 | Deployment concern |

### COULD HAVE — optional per the SRS, or extras that strengthen an evaluated challenge

| Item | Justification |
|---|---|
| TXT / Markdown / CSV ingestion | SRS explicitly says optional. The parser interface makes each one about 20 lines |
| Embedding-based similarity (in addition to TF-IDF) | SRS allows it ("may be used where required"). Improves duplicate and hallucination detection on paraphrases. Start with TF-IDF + fuzzy matching, add embeddings if time permits |
| Evaluation-mode batch ingestion (drop a folder → ingest, validate, produce a readiness report) | Directly serves the hidden-dataset evaluation. High value, low cost |
| Prerequisite graph visualization | Makes Step 26–27 visible in the demo. The underlying check is Must |
| Clause-level diff view between policy versions | Answers "What changed?" in Ch 4 visually. The underlying detection is Must |
| Second GenAI provider behind the adapter | Protects against outages or quota on the evaluation day |
| In-app notifications for due items | Nice for the employee experience; not asked for |

### WON'T HAVE — explicitly out of scope or not supported by the SRS

| Item | Reason |
|---|---|
| Live HRMS, payroll, SSO / identity-provider or commercial LMS integration | §1.4 excludes it explicitly |
| Sensitive personal data (national ID, salary, health, etc.) | Step 9: "Sensitive personal information should not be required" |
| Free-chat AI tutor / chatbot | Not in the SRS; creates an unvalidated GenAI output channel, which is the exact thing the SRS is trying to prevent |
| GenAI-based "judge" of GenAI output | Prohibited by §1.8.14 and Pipeline 2 rules |
| Leaderboards, XP, badges, gamification | Not in the SRS; feels off for compliance onboarding |
| AI-generated images, video lessons, voice | Not in the SRS; no validation path |
| SCORM/xAPI, multi-tenant SaaS, native mobile app | Not in the SRS |
| LLM-written "insights" on dashboards | Would bring back unvalidated text; dashboards show computed numbers only |

---

## 3. Requirement-by-Requirement Coverage

### 3.1 Functional Requirements (FR i – lxvi)

| FR | Requirement | Steps | P | Implementation approach | Eval |
|---|---|---|---|---|---|
| i | User authentication | — | M | Flask session auth, bcrypt-hashed passwords, CSRF protection, login rate limiting | V |
| ii | RBAC (admin, training mgr, reviewer, manager, employee) | — | M | Role → permission map in config; route decorator; server-side checks (never UI-only) | D |
| iii | Employee profile mgmt | 9 | M | Step 9 fields; no sensitive PII | V |
| iv | Role management | 2 | M | Role CRUD; new role maps to requirements via its role-description document and document `applies_to` metadata, then admin approval | Ch 3 |
| v | Document upload | 4 | M | PDF + DOCX mandatory; metadata form (category, department, version, effective/expiry, supersedes, applies-to) | V |
| vi | Document validation | 5 | M | Extension + magic-byte check, size limit, SHA-256 duplicate check, empty-text check, date sanity, version conflict check | D |
| vii | Document parsing | 6 | M | pdfplumber (page numbers), python-docx (paragraph index, heading styles); heading detection by style/numbering/font | V |
| viii | Document chunking | 7 | M | Section-aware chunking (split on headings, then by size with overlap); stable chunk IDs | V |
| ix | Source metadata | 6–7 | M | Each chunk stores doc_id, chunk_id, section_id, heading, page/paragraph, version, effective date | Ch 7 |
| x | Version control | 8 | M | Status: active / superseded / expired; `supersedes` chain; only active chunks are used for generation | Ch 4, 6 |
| xi | Requirement extraction | 11 | M | Rule-based clause classifier: modal verbs (must/shall/required → mandatory; should/recommended; may → optional), action verbs → Must Know/Complete/Demonstrate/Acknowledge; informational text excluded | D |
| xii | Role Requirement Matrix | 10 | M | Built by Python from extracted requirements + role/department applicability; admin approves; versioned | V, D |
| xiii | GenAI API integration | — | M | Provider adapter (one class per provider); key from env | V |
| xiv | Structured prompt templates | 40 | M | `prompt_templates/*.j2` with version header; registry records template hash | D |
| xv | Structured JSON output | 37 | M | Provider's native JSON-schema mode + our schema | V |
| xvi | JSON schema validation | 38 | M | Pydantic models in `schemas/`; errors stored per run | D |
| xvii | Personalized plan | 12, 16 | M | Inputs: role, department, experience, approved matrix rows, retrieved active chunks, joining date | V |
| xviii | Multi-stage onboarding | 13 | M | Stages from config; rule: Day 1 load cap (not everything on Day 1) | Ch 9 |
| xix | Module generation | 14 | M | All nine Step 14 fields | V |
| xx | Learning objectives | 14 | M | Per module; tied to requirement IDs | V |
| xxi | Checklist generation | 17 | M | Step 17 fields incl. responsible person | V |
| xxii | Task generation | 18 | M | Step 18 fields | V |
| xxiii | Scenario generation | 19 | S | Scenario = task subtype with situation, expected actions and source process; validated like tasks | V |
| xxiv | Quiz generation | 20–21 | M | 4 types; each question carries source doc/section, answer, explanation, difficulty | V |
| xxv | Quiz answer validation | 22 | M | Correct answer must be supported by the cited chunk (similarity + key-term/number match); distractors must not be supported (S-level depth) | D |
| xxvi | Assessment generation | 23 | M | Knowledge, practical, scenario, role-specific | V |
| xxvii | Rubric generation | 24 | M | Criterion, weight (weights sum to 100, checked by Python), expected performance, pass condition | V |
| xxviii | Prerequisite detection | 26 | M | Prerequisite edges from explicit cross-references in documents + configured topic dependencies; stored as a graph | V |
| xxix | Learning sequence validation | 27 | M | Topological check: missing prerequisite, wrong order, advanced before basic, assessment before content | D |
| xxx | Source citation | 15 | M | Every item must cite doc + section; uncited mandatory items fail | Ch 7 |
| xxxi | Python validation pipeline | 28 | M | `python_validation/` package, no GenAI imports (enforced by a test) | D |
| xxxii | Mandatory coverage | 28–29 | M | Set difference: matrix mandatory IDs vs generated IDs | V |
| xxxiii | Coverage score | 29 | M | Exact SRS formula | V |
| xxxiv | Traceability score | 30 | M | Items with valid, active, supporting source ÷ total items (reported separately for mandatory items) | V |
| xxxv | Hallucination detection | 31 | M | Claim-level: sentence split → factual-claim detector → support check vs cited chunk (similarity threshold + numbers/entities must appear in source) | V, Ch 8 |
| xxxvi | Contradiction detection | 33 | M | Same topic key + conflicting modality or conflicting values (days, amounts, roles); across versions, FAQ vs policy, role desc vs SOP, generated task vs rule | V, Ch 6 |
| xxxvii | Policy precedence | 34 | M | `config/precedence.yaml`; resolver explains which source won and why; hierarchy documented | Ch 6, 9 |
| xxxviii | Duplicate detection | 35 | M | Normalized text + TF-IDF cosine / fuzzy ratio for modules, tasks, checklist items, questions | D |
| xxxix | Role relevance | 36 | M | Generated item's requirement not in the role's matrix → "valid but irrelevant" flag | D |
| xl | Consistency testing | 44 | M | N controlled runs (low temperature, same inputs) | D |
| xli | Consistency score | 45 | M | Jaccard over structured sets, averaged per dimension | D |
| xlii | GenAI/Python comparison | 46 | M | Field-level match per requirement ID (Table 1 fields + Step 46 fields) with a disagreement explanation | V, D |
| xliii | Verification status | 47 | M | Item-level (§1.2 list) + plan-level (Step 47) via documented rule | V |
| xliv | Manual review queue | 48 | M | Auto-routed: unsupported, contradictory, injection-flagged, low-similarity items | V |
| xlv | Reviewer decision | 48 | M | Approve / reject / edit / regenerate (item only) / comment | V |
| xlvi | Reviewer override | 49 | M | Only Reviewer/Admin; reason required | V |
| xlvii | Audit trail | 49 | M | Append-only table; original result + decision + actor + timestamp + reason | D |
| xlviii | Prompt injection protection | 42 | M | Data delimiting in prompts, system-level rules, content sanitization, schema constraints, zero GenAI authority over status | Ch 5 |
| xlix | Adversarial doc detection | 43 | M | Pattern + heuristic scanner (imperatives aimed at AI, "ignore previous", role claims, hidden/white text, zero-width chars); chunks quarantined and shown in an ingestion report | Ch 5, D |
| l | Employee dashboard | 50 | M | Step 50 items | V |
| li | Admin dashboard | 51 | M | Step 51 items | V |
| lii | Role dashboard | 52 | S | Per-role requirements + completion stats | V |
| liii | Progress tracking | 53 | M | Step 53 items | V |
| liv | Progress assessment | 54 | S | Rule engine on due stage vs completion vs scores | — |
| lv | Weak-area detection | 56 | S | Per topic/requirement error rates + incomplete tasks + repeated wrong answers | — |
| lvi | Adaptive recommendations | 55 | S | Rule table: weakness type → recommendation; manager review when repeated | — |
| lvii | Policy update detection | 57 | M | New version upload → clause diff → changed requirement IDs | V, Ch 4 |
| lviii | Impact analysis | 58 | M | Reverse index: requirement/chunk → items → plans → employees | V, Ch 4 |
| lix | Selective regeneration | 59 | M | Regenerate only affected modules; re-validate the full plan; keep the old version for comparison | V, Ch 4 |
| lx | Search & filtering | 61 | S | Reusable server-side filter layer | Ch 9 |
| lxi | Reports | 62 | M (comparison, validation) / S (others) | Report builders over stored runs | V, D |
| lxii | Export | 63 | M (CSV) / S (PDF, Excel) | csv, openpyxl, reportlab | D |
| lxiii | API error handling | 39 | M | Typed errors: timeout, quota, auth, invalid JSON, incomplete | D |
| lxiv | Retry management | 39 | M | Max attempts + exponential backoff + repair prompt for invalid JSON; every attempt logged | D |
| lxv | Model & prompt logging | 41 | M | `generation_runs` table: request, raw response, model, params, prompt version, doc versions, latency, tokens | D |
| lxvi | Responsive web UI | — | M | Mobile-first CSS, tested at phone and desktop widths | V |

### 3.2 Steps not fully captured by an FR (easy to miss)

| Step | Requirement | P | Note |
|---|---|---|---|
| 1–3 | Dataset with realistic complexity (exceptions, cross-references, similar terminology, conditional requirements, missing info) | M | Cross-references feed prerequisite detection; conditional requirements ("if handling card data…") need a `condition` field in the matrix |
| 5 | Expiry date validation | M | Expired documents cannot be used as sources |
| 13 | "Must not assign everything on Day 1" | M | Explicit Python rule |
| 15 | Unsupported content → flagged / removed / manual review | M | All three outcomes, chosen by severity |
| 22 | Distractor validation | S | See FR xxv |
| 25 | Difficulty levels | S | |
| 32 | 3-way content classification | M | Instructional wording ("Review the…", "Discuss with your manager") is allowed without a source; factual claims are not |
| 60 | Training plan comparison | S | |
| Hidden Eval | Process unseen PDF/DOCX with no code changes | M | Test with a `hidden_test_ready/` pack we write ourselves, in a format different from our own documents |

### 3.3 Non-Functional Requirements

| NFR | Target | P | Approach |
|---|---|---|---|
| 1 Performance | ≤30s generate + validate | S | Parallel stage generation, compact retrieval, validation is fast (pure Python); measure and show timing per run |
| 2 Scalability | 1k employees, 100 roles, 1k docs | S | Indexed PostgreSQL tables, pagination, chunk retrieval by index, no full scans in request paths |
| 3 Usability | Intuitive for all user types | M | Role-specific navigation; each role sees only its own work |
| 4 Accuracy & grounding | 100% mandatory coverage before approval; valid refs | M | Enforced as a hard gate: plan cannot be "Verified" or assigned otherwise |
| 5 Availability | 99% during evaluation | S | Paid tier or keep-alive, health endpoint, graceful degradation when GenAI is down (existing plans keep working) |

### 3.4 Competition Integrity (§1.8)

| # | Rule | How the design answers it |
|---|---|---|
| 1 | Unique company pack | Our own fictional company and industry (decided with the theme) |
| 2 | Hidden documents | Generic parsers, metadata fallback, no document-specific code |
| 3 | Hidden role | Role CRUD → auto-map → admin approve → generate → validate, all in the UI |
| 4 | Policy update | Diff + impact + selective regeneration |
| 5 | Prompt injection | Scanner + quarantine + GenAI has no authority |
| 6 | Contradiction | Config-driven precedence with an explanation of each decision |
| 7 | Source traceability | Click any statement → doc, section, page, chunk text, prompt version, validation result |
| 8 | Hallucination | Retrieval confidence gate *before* generation: insufficient sources → refuse / route to review |
| 9 | Live code modification | Rules registry, YAML config, schema files, filter component |
| 10 | Deliberate defect | pytest suite that pinpoints failures by module |
| 11 | GitHub activity | Daily meaningful commits from every member |
| 12 | No hard-coded output | Every result links to a logged run; no fixture outputs |
| 14 | GenAI restriction | `python_validation/` has zero GenAI imports (test-enforced) |
| 15–16 | AI usage + AI_USAGE.md | Maintained from Day 1, not reconstructed at the end |

### 3.5 Deliverables (§1.10), all mandatory

Project report (incl. DFD, use case, activity, sequence diagrams), public GitHub repo with the prescribed folder structure, company dataset, GenAI evidence (incl. failure and retry examples), Python validation evidence, comparison report (≥100 rows), onboarding plans for 10 roles, validation report, security testing report, test cases (19 categories), installation and execution instructions, deployed URL with evaluator/admin logins, .mp4 video, 2,000+ word blog, AI_USAGE.md, team contribution record.

**Design implication:** the comparison report, validation report, plan evidence and security test report should be **generated by the application**, not written by hand. That saves time and doubles as proof of "no fabricated scores".

---

## 4. Core Features That Must Be Fully Implemented

These are the parts that evaluators will poke at live. They need to be complete and deep, not demo-deep:

1. **Ingestion that survives unseen documents.** PDF and DOCX, page/paragraph references, heading detection, version/date handling, graceful metadata fallback.
2. **Deterministic requirement extraction + approved Role Requirement Matrix.** This is the ground truth; if it is weak, every score built on it is meaningless.
3. **Structured generation with schema validation and bounded retry.** Real failure and retry logs, not simulated ones.
4. **The validation engine as a rule registry.** Each check is a small, independently testable function that returns findings. Adding a rule live means adding one function and registering it.
5. **Coverage, traceability, consistency scores.** Computed from stored data, reproducible, with the formula shown in the UI.
6. **Hallucination, unsupported-content, contradiction and duplicate detection.** Deterministic, explainable, with the evidence shown next to each flag.
7. **Precedence resolution.** Config-driven, and every resolution explains itself.
8. **GenAI vs Python comparison.** Field level, with a readable disagreement explanation.
9. **Review, override, audit.** Nothing flagged reaches an employee without a human decision; every decision is recorded.
10. **Injection defence.** Detection at ingestion *and* structural immunity at decision time.
11. **Policy change → impact → selective regeneration.** Our strongest demo moment when done right.
12. **Traceability inspector.** Any generated sentence → its evidence. This single screen answers Ch 7 and makes the whole system feel trustworthy.

---

## 5. Features to Develop After the Core System

Built in this order once the core loop (upload → matrix → generate → validate → review → assign) works end to end:

1. Progress assessment statuses + weak-area detection + adaptive recommendations (one feature set, rule-driven)
2. Role dashboard + search & filtering component
3. Full report set + PDF / Excel export
4. Scenario generation UI polish + difficulty levels + distractor validation
5. Training plan comparison (roles / departments / levels / document versions)
6. Performance tuning to hit 30s; scalability indexes; deployment hardening
7. Could-Haves by value: evaluation-mode batch ingestion → policy diff view → prerequisite graph → TXT/MD/CSV → embeddings

---

## 6. Features That Should Not Be Added Unless Justified by the SRS

A judge who has seen 30 projects will recognize these as filler:

- **Chatbot / "Ask AI" box.** An unvalidated output channel that contradicts the SRS philosophy.
- **AI-generated summaries or "insights" on dashboards.** Dashboards should show computed facts.
- **Using the LLM to validate, score, or detect contradictions.** Explicitly prohibited.
- **Gamification, avatars, confetti, 3D, particle backgrounds.** They make a compliance tool look like a template.
- **Sentiment analysis, "AI career path prediction", skill-gap radar charts with invented metrics.** Not requested; the numbers would be fabricated.
- **Vector database / LangChain agent stacks.** Unnecessary at this scale; PostgreSQL + TF-IDF (optionally embeddings) covers it, and every team member must be able to explain the code (§1.8.15).
- **Multiple dashboards showing the same numbers in different chart types.**

The "extraordinary" factor should come from **how convincingly the system proves its own correctness**, not from the number of features.

---

## 7. Recommended Development Order (5 competition days)

Dependencies drive the order: nothing validates without the matrix, and the matrix needs parsed, versioned chunks.

| Day | Build | Parallel track | End-of-day proof |
|---|---|---|---|
| **1** | Repo structure (SRS folder layout), config system, auth + RBAC, database models, upload + validation, PDF/DOCX parsing, chunking, metadata, versioning | Company scenario + requirement spreadsheet + first 10 documents; AI_USAGE.md started | Upload a PDF and a DOCX, see chunks with page/paragraph refs |
| **2** | Requirement extraction, Role Requirement Matrix + approval UI, role/employee CRUD, prompt templates, GenAI adapter, JSON schema, retry/logging, plan generation (stages, modules, objectives, checklists, tasks, quizzes, assessments, rubrics) | Remaining documents incl. conflicts, versions, injections | Generate a structured plan for one role, stored with its run log |
| **3** | Validation engine: coverage, traceability, IDs, role relevance, duplicates, sequencing/prerequisites, quiz-source, hallucination, contradiction, precedence; comparison; statuses; consistency runs | Unit tests per rule; hidden-test pack authored by a teammate who didn't write the parser | Plan shows scores, flags, comparison table and plan-level status |
| **4** | Review queue, decisions, override, audit trail; injection scanner + quarantine; policy update → impact → selective regeneration; employee/admin dashboards; progress tracking; traceability inspector | Security tests, adversarial tests, UML diagrams, report outline | Full loop incl. policy update demo |
| **5** | Role dashboard, progress assessment, weak areas, recommendations, search/filter, reports + export, plan comparison, deployment, perf tuning, UI polish | Generate plans for all 10 roles, 100-row comparison report, validation report; blog; video; README | Deployed URL, all deliverables |

Rule: **every day ends with a working, committed vertical slice.** Commits from every member every day (§1.8.11).

---

## 8. Final Scope for the Competition Version

**In scope, fully built:** all 66 functional requirements, with the Must set at production depth and the Should set functional and demonstrable; all 5 NFRs addressed and measured; all integrity challenges answerable live; all 18 deliverables.

**In scope, if time permits:** evaluation-mode batch ingestion, policy diff view, prerequisite graph, TXT/MD/CSV, embeddings, second provider.

**Out of scope:** HRMS/payroll/SSO/LMS integration, sensitive PII, chatbot, LLM-as-judge, gamification, generated media.

### What makes it extraordinary (SRS-anchored "wow" moments)

Each of these is a presentation of a required feature, not an extra feature:

1. **Traceability Inspector.** Click any sentence in any plan → source document, section, page, the exact highlighted chunk, the prompt version and model, and each validation check it passed or failed. (Ch 7)
2. **Verification Ledger.** Side-by-side GenAI vs Python per requirement, field by field, with plain-English disagreement explanations and the coverage formula computed live. (FR xlii)
3. **Policy Change Walkthrough.** Upload v2 → clause diff → "4 modules, 11 questions, 23 employees affected" → regenerate only those → before/after scores. (Ch 4)
4. **Injection Quarantine Report.** Ingestion shows the exact malicious lines, why they were flagged, and proof that the plan's status was unaffected. (Ch 5)
5. **Honest Refusal.** Ask for training on a topic not in the documents → "Insufficient approved sources", with the nearest sections found and their similarity scores, routed to review. (Ch 8)
6. **Precedence Explanations.** Every resolved conflict shows both clauses and the rule that decided it. (Ch 6)
7. **Pipeline Run Timeline.** Each generation shows parse → retrieve → generate → schema → validate → compare with timings and retry attempts. Engineering made visible.

---

*Next step: choose the fictional company / industry and the visual theme & palette. The theme should suit an enterprise trust-and-verification product: calm, precise, auditable. Not a playful learning app.*
