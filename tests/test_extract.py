"""Extraction tests on REAL stored TED notices (data/raw/html)."""

import json
from pathlib import Path

import pytest

from extract import _parse_number, check_schema, extract_rules
from parse_notice import html_to_text
from run_demo import DATA, build_all

HTML = DATA / "raw" / "html"


def extract(notice_id: str) -> dict:
    return extract_rules(html_to_text((HTML / f"{notice_id}.html").read_text(encoding="utf-8")))


@pytest.mark.parametrize("raw, value", [("138 100,00", 138100.0), ("1.300.000,00", 1300000.0), ("1,00", 1.0)])
def test_parse_eu_number(raw, value):
    assert _parse_number(raw) == value


def test_awarded_value_preferred_over_placeholder_estimate():
    out = extract("804251-2026")  # estimate 1,00 EUR, awarded 138 100,00 EUR
    assert (out["amount_value"], out["currency"], out["amount_kind"]) == (138100.0, "EUR", "awarded")
    assert out["needs_manual_review"] is False


def test_framework_ceiling_detected():
    out = extract("672950-2026")
    assert out["amount_value"] == 150_000_000.0
    assert out["amount_kind"] == "framework_maximum"
    assert out["is_framework_agreement"] is True


def test_placeholder_and_contradiction_become_null_with_review():
    out = extract("785099-2026")  # "RV ..." title, "No framework agreement", value 1,00 EUR
    assert out["amount_value"] is None and out["currency"] is None
    assert out["is_framework_agreement"] is None
    assert out["needs_manual_review"] is True
    assert "placeholder" in out["review_reason"] and "framework" in out["review_reason"]


def test_unpublished_value_is_null_not_guessed():
    out = extract("796992-2026")
    assert out["amount_value"] is None
    assert "unpublished" in out["review_reason"]


def test_all_stored_notices_match_schema():
    for path in sorted(HTML.glob("*.html")):
        assert check_schema(extract(path.stem)) == [], path.name


def test_check_schema_rejects_bad_llm_output():
    good = extract("804251-2026")
    assert check_schema({**good, "amount_value": "138100"}) == ["bad type for amount_value: '138100'"]
    assert check_schema({**good, "amount_kind": "guess"}) == ["bad type for amount_kind: 'guess'"]
    missing = {k: v for k, v in good.items() if k != "buyer"}
    assert check_schema(missing) == ["missing field: buyer"]


def test_offline_run_reproduces_committed_sample_output():
    expected = json.loads((DATA / "sample_output.json").read_text(encoding="utf-8"))
    assert build_all(extract_rules, "rules") == expected
