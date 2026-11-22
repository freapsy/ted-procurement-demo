import pytest

from validate import validate_records

BASE = {
    "notice_id": "804251-2026",
    "source_url": "https://ted.europa.eu/en/notice/804251-2026/html",
    "fetched_at_utc": "2026-11-22T13:56:40+00:00",
    "publication_date": "2026-11-17",
    "amount_value": 138100.0,
    "currency": "EUR",
    "is_framework_agreement": False,
    "is_framework_ceiling": False,
    "needs_manual_review": False,
    "review_reason": None,
}


def status(**changes) -> tuple[str, str]:
    rec = validate_records([{**BASE, **changes}])[0]
    return rec["validation_status"], rec["validation_notes"]


def test_clean_record_is_ok():
    assert status() == ("ok", "")


@pytest.mark.parametrize("changes, message", [
    ({"currency": "EURO"}, "invalid currency"),
    ({"currency": None}, "invalid currency"),
    ({"amount_value": 0}, "amount must be > 0"),
    ({"amount_value": -5.0}, "amount must be > 0"),
    ({"amount_value": None}, "currency set without amount"),
    ({"amount_value": None, "currency": None}, "not flagged for review"),
    ({"publication_date": "17/11/2026"}, "not an ISO date"),
    ({"fetched_at_utc": "2026-11-22T13:56:40"}, "not an ISO UTC timestamp"),  # naive = no timezone
    ({"source_url": ""}, "source_url"),
    ({"notice_id": "abc"}, "invalid notice_id"),
    ({"is_framework_ceiling": True}, "no framework agreement with amount"),
])
def test_errors(changes, message):
    result, notes = status(**changes)
    assert result == "error" and message in notes


def test_null_amount_with_review_is_allowed():
    result, notes = status(amount_value=None, currency=None, needs_manual_review=True, review_reason="no amount found")
    assert result == "needs_review" and "no amount found" in notes


def test_framework_ceiling_is_flagged_not_rejected():
    result, notes = status(is_framework_agreement=True, is_framework_ceiling=True)
    assert result == "needs_review" and "ceiling" in notes


def test_duplicate_notice_ids():
    records = validate_records([dict(BASE), dict(BASE)])
    assert all(r["validation_status"] == "error" and "duplicate" in r["validation_notes"] for r in records)
