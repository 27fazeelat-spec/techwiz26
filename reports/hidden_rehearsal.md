# Hidden-evaluation rehearsal

Run on 2026-09-25 against a throw-away local database (baseline: the Aurelle sample documents). Ingesting the pack, detecting changes and conflicts, and building the new draft matrix took **4.6 s**. No code or configuration was changed for these files.

Rebuild with `python tools/build_hidden_pack.py` and `python hidden_test_ready/rehearse.py`.

| Case | SRS hidden item | File | What SkillSprint did | Expected |
|---|---|---|---|---|
| H01 | New company policy | `VAL-01_v1.0.docx` | status **active**; 4 requirement(s); types Must Complete, Must Know; roles DMG, FOA, NAU; 4 with no stage in the text (default stage used); conflict CF-0029 with R-SOP-FO-03-001 (auto resolved) | Ingested as active; new requirements for Front Office Associates and Duty Managers |
| H02 | Revised existing policy | `GDP-01_v3.0.pdf` | status **active**; 10 requirement(s); types Must Complete, Must Know; roles ALL, FOA; 9 with no stage in the text (default stage used); conflict CF-0025 with R-MEM-01-001 (auto resolved); conflict CF-0030 with R-GDP-01-004 (auto resolved); change v2.0 to v3.0: unchanged 8, changed 1, added 1 | v3 replaces v2; the change record shows the 7 to 3 day retention change and one added consent rule |
| H03 | New job role | `ROL-04_v1.0.docx` | status **active**; 3 requirement(s); types Must Know; roles NAU; 3 with no stage in the text (default stage used); conflict CF-0028 with R-FAQ-02-001 (auto resolved) | Once the Night Auditor role is added on the Job roles page, existing night audit and cash rules map to it |
| H04 | Conflicting FAQ | `FAQ-02_v1.0.docx` | status **active**; 2 requirement(s); types Must Know, Optional; roles FOA, NAU; 2 with no stage in the text (default stage used); conflict CF-0026 with R-PCH-01-005 (auto resolved); conflict CF-0028 with R-ROL-04-002 (auto resolved) | Its single-person count conflicts with the two-person float count in PCH-01; the policy wins |
| H05 | Outdated SOP | `SOP-FO-02_v1.0.pdf` | status **superseded**; 5 requirement(s); types Must Know; roles ALL, FNA; 5 with no stage in the text (default stage used) | Recognised as older than the active v1.2: filed as superseded, never active |
| H06 | Missing / incomplete requirement | `LPP-01_v1.0.pdf` | status **active**; 2 requirement(s); types Must Know; roles ALL; 2 with no stage in the text (default stage used); unresolved reference: Annex B | The reference to Annex B is recorded as unresolved |
| H07 | Prompt-injection document | `PLS-01_v1.0.docx` | status **active**; 2 requirement(s); types Must Know; roles ALL; 2 with no stage in the text (default stage used); security: metadata_instruction (high) | The instruction in the DOCX file properties is recorded as a high-severity finding and never reaches a prompt |
| H08 | New compliance requirement | `CMP-02_v1.0.pdf` | status **active**; 1 requirement(s); types Must Acknowledge; roles ALL | A mandatory Week 1 rule for all employees; it enters every role in the next matrix |
| H09 | Role-specific exception | `SOP-FO-03_v1.0.docx` | status **active**; 2 requirement(s); types Must Know, Optional; roles FOA; 2 with no stage in the text (default stage used); conflict CF-0027 with R-SOP-FO-01-009 (manual review); conflict CF-0029 with R-VAL-01-002 (auto resolved) | A permission that applies to Front Office Associates, with its condition kept |
| H10 | Ambiguous clause | `TRN-01_v1.0.pdf` | status **active**; 1 requirement(s); types Recommended; roles ALL; 1 with no stage in the text (default stage used) | Weak wording and no stage: extracted as a recommendation with a default stage, for review |

## Requirements per role, approved matrix before and draft matrix after

| Role | Before | After |
|---|---|---|
| DMG | 110 | 118 |
| FBA | 95 | 101 |
| FNA | 88 | 94 |
| FOA | 107 | 119 |
| GRE | 83 | 89 |
| HKS | 91 | 97 |
| HRE | 78 | 84 |
| MTT | 79 | 85 |
| NAU | 0 | 115 |
| RVA | 78 | 84 |
| SEE | 82 | 88 |

Compare the two columns in *What SkillSprint did* and *Expected*; a difference is a finding to fix, not something to hide.
