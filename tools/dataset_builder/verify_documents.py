"""Verify the generated sample documents against the requirements register.

Reads every file in sample_documents/ the way a parser would (pdfplumber for PDF,
python-docx for DOCX incl. tables, footers and hidden runs) and checks:

  1. every register clause appears verbatim in its document's register version
  2. no stray obligation wording (must/should/may/...) outside registered clauses,
     which would make the register an inaccurate answer key
  3. no alcohol-related wording anywhere (project constraint)

Usage:  python tools/dataset_builder/verify_documents.py
"""
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

import pdfplumber
from docx import Document

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "sample_documents"
DATASET = ROOT / "documentation" / "dataset"

OBLIGATION = re.compile(
    r"\b(must|shall|should|may|can|required?|requires|prohibited|not permitted|"
    r"encouraged|entitled|responsible for|need to|have to|expected to|will not be approved)\b",
    re.I)
ALCOHOL = re.compile(r"\b(alcohol\w*|liquor|bar service|bar staff|bar shift|licensed outlet|"
                     r"wine|beer|cocktail|intoxicat\w*|spirits|minibar|welcome drink)\b", re.I)
# Planted adversarial payloads legitimately contain obligation words.
ADVERSARIAL_MARKERS = ("assistant:", "system:", "message from the ceo", "ai systems", "ignore")
NO_REQUIREMENT_CATEGORIES = {"External", "Irrelevant"}


def norm(text):
    text = text.replace("​", "").replace(" ", " ")
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).strip()


def read_pdf(path):
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages), len(pdf.pages)


def read_docx(path):
    doc = Document(path)
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    for section in doc.sections:
        parts.extend(p.text for p in section.footer.paragraphs)
    return "\n".join(parts), None


def sentences(text):
    flat = norm(text)
    return [s for s in re.split(r"(?<=[.!?])\s+", flat) if s]


def main():
    with open(DATASET / "02_Document_Register.csv", encoding="utf-8") as f:
        register_docs = list(csv.DictReader(f))
    with open(DATASET / "03_Requirements_Register.csv", encoding="utf-8") as f:
        reqs = list(csv.DictReader(f))

    clauses = defaultdict(list)
    for r in reqs:
        clauses[r["doc_id"]].append(r)

    # The register version of a document is its Active (or, if none, Expired) version.
    register_version = {}
    for d in register_docs:
        if d["status"] in ("Active", "Expired") and d["doc_id"] not in register_version:
            register_version[d["doc_id"]] = d

    problems, rows = [], []
    expected_files = {f"{d['doc_id']}_v{d['version']}" for d in register_docs}
    doc_files = sorted(p for p in DOCS.glob("*.*") if p.suffix in (".pdf", ".docx"))
    found_files = {p.stem for p in doc_files}
    for missing in sorted(expected_files - found_files):
        problems.append(f"missing file for register entry {missing}")
    for extra in sorted(found_files - expected_files):
        problems.append(f"file not in document register: {extra}")

    for path in doc_files:
        text, pages = read_pdf(path) if path.suffix == ".pdf" else read_docx(path)
        doc_id, version = path.stem.rsplit("_v", 1)
        flat = norm(text)

        for m in ALCOHOL.finditer(flat):
            problems.append(f"{path.name}: alcohol-related wording '{m.group(0)}'")

        reg = register_version.get(doc_id)
        is_register_file = reg is not None and reg["version"] == version
        found = total = 0
        if is_register_file and reg["category"] not in NO_REQUIREMENT_CATEGORIES:
            doc_clauses = [norm(r["clause_text"]) for r in clauses[doc_id]]
            for r, clause in zip(clauses[doc_id], doc_clauses):
                total += 1
                if clause in flat:
                    found += 1
                else:
                    problems.append(f"{path.name}: clause {r['req_id']} not found verbatim")
            for s in sentences(text):
                if not OBLIGATION.search(s) or s.endswith("?"):
                    continue
                if any(k in s.lower() for k in ADVERSARIAL_MARKERS):
                    continue
                if not any(c in s or s in c for c in doc_clauses):
                    problems.append(f"{path.name}: stray obligation wording: \"{s[:110]}\"")
        rows.append((path.name, pages, len(flat.split()), f"{found}/{total}" if total else "-"))

    print(f"{'File':<34}{'Pages':>6}{'Words':>7}   Clauses")
    print("-" * 60)
    for name, pages, words, clause_info in rows:
        print(f"{name:<34}{(pages or ''):>6}{words:>7}   {clause_info}")
    print(f"\n{len(rows)} files checked.")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print("  - " + p)
        sys.exit(1)
    print("All clauses present, no stray obligations, no alcohol wording.")


if __name__ == "__main__":
    main()
