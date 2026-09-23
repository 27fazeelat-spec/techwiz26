"""Find contradictions between current requirements.

  cross_document - two different documents, same topic, and a concrete disagreement signal
  version        - a requirement whose facts changed between a superseded version and the current one
Both inputs are plain dicts, so the detector has no database dependency and is easy to test.
"""
import math

from contradiction_checks.signals import differences, glossary_tokens, topic_similarity, topic_words

MIN_SIMILARITY = 0.4       # general topic match
CLASH_SIMILARITY = 0.25    # enough when one clause forbids what the other allows, on a glossary term
# Both thresholds were tuned on the Aurelle sample dataset (12 of 12 planned conflicts found); unseen
# documents may need them adjusted, which is why every detected conflict is shown with its evidence.


def _idf(texts):
    """Inverse document frequency of topic words across all current requirement clauses."""
    df = {}
    for t in texts:
        for w in topic_words(t):
            df[w] = df.get(w, 0) + 1
    n = len(texts) or 1
    return {w: math.log(1 + n / c) for w, c in df.items()}


def _strongest_per_document(conflicts):
    """One clause can resemble several clauses of another document (an FAQ answer about leave matches every
    leave rule). Keep only its strongest pairing with each other document."""
    best = {}
    for c in conflicts:
        for this, other in (("left", "right"), ("right", "left")):
            key = (c[this]["id"], c[other]["doc_id"])
            if key not in best or c["similarity"] > best[key]["similarity"]:
                best[key] = c
    keep = {id(c) for c in best.values()}
    return [c for c in conflicts if id(c) in keep and
            best[(c["left"]["id"], c["right"]["doc_id"])] is c and best[(c["right"]["id"], c["left"]["doc_id"])] is c]


def detect(current, previous_versions=()):
    """current: dicts {id, req_id, doc_id, version, tier, category, text, strength}.
    previous_versions: dicts for superseded versions, each with current_id = the successor's id.
    Returns conflict dicts {kind, left, right, differences, similarity, shared}.
    """
    conflicts = []
    items = [r for r in current if r["tier"] > 0]
    idf = _idf([r["text"] for r in items])
    terms = glossary_tokens()
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a["doc_id"] == b["doc_id"]:
                continue
            score, shared = topic_similarity(a["text"], b["text"], idf)
            if score < CLASH_SIMILARITY:
                continue
            diffs = differences(a, b)
            if not diffs:
                continue
            # Same topic: a strong weighted overlap backed by two shared words or a curated glossary term;
            # or, for a direct prohibition-versus-permission clash, a moderate overlap on a glossary term.
            strong = score >= MIN_SIMILARITY and (len(shared) >= 2 or shared & terms)
            clash = any(d["type"] == "permission" and {d["left"], d["right"]} & {"prohibits", "restricts"}
                        for d in diffs) and shared & terms
            if strong or clash:
                conflicts.append({"kind": "cross_document", "left": a, "right": b, "differences": diffs,
                                  "similarity": round(score, 2), "shared": sorted(shared)})
    conflicts = _strongest_per_document(conflicts)
    by_id = {r["id"]: r for r in current}
    for old in previous_versions:
        new = by_id.get(old["current_id"])
        if new is None or new["text"] == old["text"]:
            continue
        diffs = differences(new, old)
        if diffs:
            conflicts.append({"kind": "version", "left": new, "right": old, "differences": diffs,
                              "similarity": 1.0, "shared": []})
    return conflicts
