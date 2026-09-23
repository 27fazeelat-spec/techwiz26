from datetime import date

from document_processing.metadata import version_key
from document_processing.versioning import compute_statuses

TODAY = date(2026, 9, 23)


def v(version, effective=None, expiry=None, draft=False):
    return {"version": version, "effective_date": effective, "expiry_date": expiry, "is_draft": draft}


def test_latest_effective_version_is_active_and_older_is_superseded():
    result = compute_statuses([v("1.0", date(2024, 1, 1)), v("2.0", date(2026, 4, 1))], TODAY)
    assert result["2.0"] == ("active", None)
    assert result["1.0"] == ("superseded", "2.0")


def test_future_version_is_scheduled_and_current_stays_active():
    result = compute_statuses([v("1.0", date(2025, 1, 15)), v("2.0", date(2026, 11, 1))], TODAY)
    assert result["1.0"][0] == "active" and result["2.0"][0] == "scheduled"


def test_draft_never_becomes_active():
    result = compute_statuses([v("2.0", date(2026, 2, 15)), v("3.0-DRAFT", draft=True)], TODAY)
    assert result["3.0-DRAFT"][0] == "draft" and result["2.0"][0] == "active"


def test_expired_without_replacement():
    result = compute_statuses([v("1.0", date(2023, 4, 1), date(2026, 3, 31))], TODAY)
    assert result["1.0"][0] == "expired"


def test_superseded_version_past_expiry_is_superseded_not_expired():
    result = compute_statuses([v("1.0", date(2024, 1, 1), date(2026, 3, 31)), v("2.0", date(2026, 4, 1))], TODAY)
    assert result["1.0"][0] == "superseded"


def test_version_ordering_is_numeric():
    assert version_key("2.10") > version_key("2.9")
    assert version_key("3.0-DRAFT") == (3, 0)
