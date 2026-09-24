# hidden_test_ready

A rehearsal for the hidden evaluation (SRS §1.9): ten documents SkillSprint has never been tuned on, one for
each kind of file the evaluators may upload, plus a script that ingests them and reports what happened.

The files are written differently from the main Aurelle dataset on purpose: no letterhead, no metadata table,
a different heading style in each file, a DOCX with no heading styles at all, metadata as loose
`Label: value` lines or only through `upload_manifest.csv` (the upload form), and one instruction hidden in the
DOCX file properties.

| Case | SRS hidden item | File | What should happen |
|---|---|---|---|
| H01 | New company policy | `VAL-01_v1.0.docx` | Active; new rules for Front Office Associates and Duty Managers |
| H02 | Revised existing policy | `GDP-01_v3.0.pdf` | Replaces v2; change record shows 7 → 3 day retention and one added consent rule |
| H03 | New job role | `ROL-04_v1.0.docx` | After *Night Auditor* is added on the Job roles page, existing night audit and cash rules map to it |
| H04 | Conflicting FAQ | `FAQ-02_v1.0.docx` | Conflicts with the two-person float count in PCH-01; the policy wins |
| H05 | Outdated SOP | `SOP-FO-02_v1.0.pdf` | Older than the active v1.2: filed as superseded, never active |
| H06 | Missing / incomplete requirement | `LPP-01_v1.0.pdf` | "Annex B (to be issued)" recorded as an unresolved reference |
| H07 | Prompt-injection document | `PLS-01_v1.0.docx` | Instruction in the file properties recorded as a high-severity finding; never reaches a prompt |
| H08 | New compliance requirement | `CMP-02_v1.0.pdf` | Mandatory Week 1 rule for all roles in the next matrix |
| H09 | Role-specific exception | `SOP-FO-03_v1.0.docx` | Permission for Front Office Associates with its condition; flagged against the general key rule |
| H10 | Ambiguous clause | `TRN-01_v1.0.pdf` | Weak wording, no stage: a recommendation with a default stage, for review |

## Running the rehearsal

```
python tools/build_hidden_pack.py        # (re)build documents/ from the text in the script
python hidden_test_ready/rehearse.py     # writes reports/hidden_rehearsal.md
```

`rehearse.py` never touches the hosted database. It clears `DATABASE_URL`, creates a new SQLite file in the
temp folder, loads the Aurelle sample documents as the baseline, ingests this folder, detects changes and
conflicts, builds a draft matrix, writes the report and deletes the file. No GenAI call is made.
The latest result is in [`reports/hidden_rehearsal.md`](../reports/hidden_rehearsal.md).

## On the day

Put the evaluators' files in a folder and either upload them on **Documents > Upload** or run:

```
python -m flask --app run ingest-folder <folder> --report reports/hidden_readiness.md
```

The readiness report lists, per file, how it was read, where each metadata value came from, what was
extracted, what the security scan flagged, and why anything was rejected. Then run conflict detection and
build a new matrix from the Role matrix page.

## What the rehearsal changed

The first run rejected seven of the ten files. The fixes were made in the parser, not in the documents:
document IDs are now read from file names such as `GDP-01_v3.0.pdf`, metadata lines that a PDF reader joins
into one paragraph are split again, an unnumbered first line in a larger bold font is taken as the title,
numbered bold headings at body size are recognised, and instructions hidden in DOCX file properties are
scanned. Extraction accuracy on the main dataset was re-measured afterwards and did not change.
