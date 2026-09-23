"""Metadata checks: required fields, formats, dates, category, department, version conflicts."""
import re

DOC_ID = re.compile(r"^[A-Z0-9]{2,6}(-[A-Z0-9]{1,6}){1,3}$")
VERSION = re.compile(r"^\d+(\.\d+){0,3}(-[A-Za-z]+)?$")


def validate_metadata(meta, categories, departments, existing_versions=()):
    """Mutates meta (normalises category) and returns (errors, warnings)."""
    errors, warnings = [], []

    doc_id = (meta.get("doc_id") or "").strip()
    if not doc_id:
        errors.append("No document ID was found in the document. Enter it on the upload form.")
    elif not DOC_ID.match(doc_id):
        errors.append(f"'{doc_id}' is not a valid document ID (expected a form like GDP-01 or SOP-FO-01).")

    version = (meta.get("version") or "").strip()
    if not version:
        errors.append("No version was found in the document. Enter it on the upload form.")
    elif not VERSION.match(version):
        errors.append(f"'{version}' is not a valid version (expected a form like 2.0 or 3.0-DRAFT).")
    elif version in existing_versions:
        errors.append(f"{doc_id} version {version} already exists with different content. "
                      "Upload a new version number or check the file.")

    if not meta.get("title"):
        warnings.append("No title found; the document ID is used as the title.")
        meta["title"] = doc_id

    category = meta.get("category")
    if not category:
        warnings.append("No category given; the document is filed as 'Other' and cannot create requirements.")
        meta["category"] = "Other"
    elif category not in categories:
        warnings.append(f"Unknown category '{category}'; filed as 'Other'.")
        meta["category"] = "Other"

    department = meta.get("owner_department")
    if department and department not in departments:
        warnings.append(f"Department '{department}' is not in the configured list.")

    effective, expiry = meta.get("effective_date"), meta.get("expiry_date")
    if not effective and not meta.get("is_draft"):
        warnings.append("No effective date; the document is treated as effective from upload.")
    if effective and expiry and expiry < effective:
        errors.append(f"The expiry date ({expiry}) is before the effective date ({effective}).")
    return errors, warnings
