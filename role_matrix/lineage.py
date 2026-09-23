"""Requirement lineage across document versions.

When version 2 of a document arrives, each of its clauses is matched to the clause it replaces in
version 1: first within the same section, then anywhere in the document. A match keeps the
requirement ID (so impact analysis can follow it); an unmatched clause gets a new ID.
"""
from difflib import SequenceMatcher


def _ratio(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def match(new_items, previous_items, same_section_min, any_section_min):
    """new_items/previous_items: lists of dicts with 'section_id' and 'text' (previous also 'req_id').

    Returns a list aligned with new_items: (previous_item | None, change) where change is
    'unchanged', 'changed' or 'added'.
    """
    available = list(previous_items)
    results = []
    for item in new_items:
        best, best_score = None, 0.0
        for prev in available:
            score = _ratio(item["text"], prev["text"])
            threshold = same_section_min if prev["section_id"] == item["section_id"] else any_section_min
            if score >= threshold and score > best_score:
                best, best_score = prev, score
        if best is None:
            results.append((None, "added"))
        else:
            available.remove(best)
            results.append((best, "unchanged" if best["text"] == item["text"] else "changed"))
    return results


def removed(previous_items, matched):
    ids = {id(p) for p, _ in matched if p is not None}
    return [p for p in previous_items if id(p) not in ids]
