"""Document version control (SRS Step 8).

Decides which version of a document lineage is the valid source on a given date:
  draft      - marked draft / not approved: never a source
  scheduled  - effective date still in the future
  active     - the latest effective, approved version
  expired    - the latest effective version, but past its expiry date with no replacement
  superseded - an older version replaced by a later one
"""
from document_processing.metadata import version_key


def compute_statuses(versions, today):
    """versions: [{version, effective_date, expiry_date, is_draft}] -> {version: (status, superseded_by)}."""
    result, candidates = {}, []
    for v in versions:
        if v.get("is_draft"):
            result[v["version"]] = ("draft", None)
        elif v.get("effective_date") and v["effective_date"] > today:
            result[v["version"]] = ("scheduled", None)
        else:
            candidates.append(v)
    if candidates:
        latest = max(candidates, key=lambda v: version_key(v["version"]))
        for v in candidates:
            if v is latest:
                expired = v.get("expiry_date") and v["expiry_date"] < today
                result[v["version"]] = ("expired" if expired else "active", None)
            else:
                result[v["version"]] = ("superseded", latest["version"])
    return result
