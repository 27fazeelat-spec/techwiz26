# Evidence exports

Exported on 2026-09-25 from the live Aurelle workspace (fictional company) with a read-only script: the same
report queries as the *Reports* page, nothing written to the database. The audit-trail report is left out on
purpose because it holds sign-in records.

| File | What it shows | Rows |
|---|---|---|
| `comparison.csv/.pdf` | GenAI output vs Python validation, field by field | 893 |
| `validation.csv/.pdf` | Validation result per plan | 11 |
| `findings.csv/.pdf` | Every validation finding with its rule | 833 |
| `hallucination.csv/.pdf` | Content the cited source does not support | 79 |
| `traceability.csv/.pdf` | Each generated item traced to requirement, document version and section | 1374 |
| `mandatory_training.csv/.pdf` | Mandatory requirements per plan and whether each is covered | 805 |
| `role_coverage.csv/.pdf` | Requirements, employees and coverage per role | 10 |
| `policy_coverage.csv/.pdf` | Requirements per source document and how many plans use them | 30 |
| `progress.csv/.pdf` | Employee progress and status | 12 |
| `assessment_results.csv/.pdf` | Quiz and assessment attempts | 2 |
| `security.csv/.pdf` | Prompt-injection findings caught at ingestion | 16 |
| `plans_by_role.csv` | Current plan for one employee in each of the 10 roles, with scores | 11 |
| `genai_runs.csv` | Every Gemini call: phase, model, prompt version, attempts, retries, errors, latency, tokens | 126 |
| `genai_request_response.json` | A full request and response for one outline and one module call, and the last five calls that failed or needed a retry | |

Plans show *Incomplete* until a person has decided every review item and assigned them; that is the review
gate, not a generation failure. One FOA version is *Failed*: a Gemini error kept as evidence of the failure path.
