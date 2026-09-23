"""Requirement extraction: measured against the gold register, plus focused unit checks."""
from sqlalchemy import select

from database.models import Requirement
from role_matrix.extractor import Rules, extract_from_chunk
from tools.extraction_accuracy import evaluate


def extract(sentence):
    return extract_from_chunk(sentence, "TST-01", "Test Policy", ["1. Test"], ["Duty Manager"], Rules())


def test_accuracy_against_the_gold_register(corpus):
    session, _ = corpus
    m = evaluate(session)
    print(f"\nrecall {m['recall']:.1%}  precision {m['precision']:.1%}  mandatory {m['mandatory_accuracy']:.1%}  "
          f"type {m['type_accuracy']:.1%}  roles {m['roles_jaccard']:.1%}  stage {m['stage_accuracy']:.1%}")
    # Thresholds are set just below today's measured values, so a regression fails the build.
    assert m["recall"] >= 0.97
    assert m["precision"] >= 0.97
    assert m["mandatory_accuracy"] >= 0.97
    assert m["section_accuracy"] >= 0.97
    assert m["type_accuracy"] >= 0.85
    assert m["roles_jaccard"] >= 0.78


def test_modality_and_informational_text():
    assert extract("Employees must lock their workstations.")[0].mandatory
    assert extract("Staff should rotate floors monthly to balance workload.")[0].req_type == "Recommended"
    assert extract("Employees may apply for an internal transfer after a year.")[0].req_type == "Optional"
    assert extract("The Aurelle Academy offers e-learning and coaching.") == []
    assert extract("How far ahead do I apply for leave?") == []


def test_facts_and_conditions():
    item = extract("At Malaysian properties, guests must sign the consent notice within 7 days.")[0]
    assert item.condition == {"field": "property.country", "op": "eq", "value": "Malaysia",
                              "text": "At Malaysian properties"}
    assert {"kind": "number", "value": 7.0, "unit": "day", "span": "7 days"} in item.facts
    item = extract("Injuries must be reported to the Duty Manager within 15 minutes.")[0]
    assert {"kind": "actor", "value": "Duty Manager", "unit": "actor", "span": "Duty Manager"} in item.facts


def test_requirement_ids_survive_a_new_version(corpus):
    session, _ = corpus
    v1 = {r.text: r.req_id for r in session.scalars(select(Requirement).where(
        Requirement.doc_id == "GDP-01", Requirement.version == "1.0"))}
    v2 = session.scalars(select(Requirement).where(Requirement.doc_id == "GDP-01", Requirement.version == "2.0")).all()
    retention = next(r for r in v2 if "7 days after check-out" in r.text)
    assert retention.lineage_change == "changed"
    assert retention.req_id == v1[next(t for t in v1 if "30 days after check-out" in t)]
    phones = next(r for r in v2 if "personal mobile phones" in r.text)
    assert phones.lineage_change == "added" and phones.req_id not in v1.values()


def test_cross_references_are_resolved(corpus):
    session, _ = corpus
    from src.services.requirements import link_requirements
    link_requirements()
    pets = session.scalar(select(Requirement).where(Requirement.text.like("%Pet Policy (PET-01)%"),
                                                    Requirement.version == "2.0"))
    assert any(ref.get("doc_id") == "PET-01" and ref["resolved"] is False for ref in pets.cross_refs)
    waiver = session.scalar(select(Requirement).where(Requirement.text.like("%in line with REV-01 Section 3.4%"),
                                                      Requirement.version == "2.0"))
    assert any(ref.get("doc_id") == "REV-01" and ref["resolved"] for ref in waiver.cross_refs)
