# Aurelle Company Dataset: Blueprint

This folder is the **authoring specification and answer key** for the Aurelle Hotels & Residences document collection. It is written *before* the documents themselves, so every conflict, version change and adversarial case is planned and nothing is left to chance.

| File | Purpose |
|---|---|
| [01_Company_Profile.md](01_Company_Profile.md) | Company, properties, departments, the 10 roles, demo employees, precedence hierarchy, document-writing conventions |
| [02_Document_Register.csv](02_Document_Register.csv) | Every document and every version: ID, category, tier, format, status, dates, supersedes, planned test cases |
| [03_Requirements_Register.csv](03_Requirements_Register.csv) | Every requirement the documents must contain, with the exact clause wording, type, roles, stage, prerequisites and case tags |
| [04_Test_Cases.md](04_Test_Cases.md) | Conflicts, version changes, adversarial cases, missing information, conditional rules, prerequisite chains, hallucination probes, hidden-pack rehearsal, each with the expected system behaviour |
| [check_blueprint.py](check_blueprint.py) | Verifies the blueprint meets every SRS dataset minimum and is internally consistent |

The documents themselves (44 PDF/DOCX files) are in `sample_documents/`, generated from editable sources by [tools/dataset_builder](../../tools/dataset_builder/README.md).

## The one rule about this folder

**The application must never read these files.**

The Role Requirement Matrix must be *extracted by Python from the uploaded documents* (SRS Steps 10–11). If the app loaded this register, the matrix would be hard-coded, which is prohibited by §1.8.12 and would fail the hidden-document evaluation anyway.

This register is used for:

1. **Writing the documents.** Authors paste the `clause_text` into the right document and section, surrounded by realistic informational text.
2. **Measuring the extractor.** `tests/` compares what the app extracts against this register (precision / recall on requirements, accuracy on mandatory flag, type and roles). That gives us an honest, reportable extraction accuracy figure.
3. **Evidence for the project report.** The dataset deliverable (§1.10.3) asks for the requirement matrix, metadata, version history, conflict cases and adversarial cases. These files are that evidence.

## Requirement ID convention

`R-<DOC>-<NNN>`: the document code, then the requirement's order of appearance in that document (e.g. `R-GDP-004`). The app assigns IDs the same way: by document and reading order. When a new version of a document arrives, each requirement is matched to its predecessor by section and clause similarity, so the ID survives the revision. That lineage is what makes policy-update impact analysis possible.

## SRS minimums (verified by `check_blueprint.py`)

| SRS minimum | Required | Blueprint |
|---|---|---|
| Company documents | 20 | 31 documents (44 files incl. versions and draft) |
| Job roles | 10 | 10 (+1 hidden-role rehearsal) |
| Identifiable requirements | 150 | 185 |
| Mandatory requirements | 50 | 167 |
| Role-specific requirements | 30 | 132 |
| Conflicting / ambiguous cases | 10 | 13 |
| Policy version changes | 10 | 12 |
| Adversarial / injection cases | 10 | 12 |

Run: `python documentation/dataset/check_blueprint.py`
