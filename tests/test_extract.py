"""Extraction tests on REAL stored TED notices (data/raw/html)."""

import json
from pathlib import Path

import pytest

from extract import _parse_number, check_llm_output, check_schema, extract_rules
from parse_notice import html_to_text
from run_demo import DATA, build_all, build_record

HTML = DATA / "raw" / "html"


FIXTURES = Path(__file__).parent / "fixtures"


def text_of(notice_id: str, folder: Path = HTML) -> str:
    return html_to_text((folder / f"{notice_id}.html").read_text(encoding="utf-8"))


def extract(notice_id: str) -> dict:
    return extract_rules(text_of(notice_id))


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
    assert "unpublished" in out["review_reason"] and "unpublished" in out["evidence"]


def test_framework_awarded_value_is_not_the_ceiling():
    # Real notice outside the sample (Danish MoD, fetched 2026-11-22): awarded 25 M DKK, maximum 75 M DKK.
    rec = build_record({"publication-number": "118509-2025", "publication-date": "2025-02-21"}, {},
                       "", extract_rules(text_of("118509-2025", FIXTURES)), "rules")
    assert (rec["amount_value"], rec["currency"], rec["amount_kind"]) == (25_000_000.0, "DKK", "awarded")
    assert rec["is_framework_agreement"] is True and rec["is_framework_ceiling"] is False


def test_lot_value_is_not_reported_as_notice_total():
    # Synthetic, TED layout: no procedure-level value, only an estimate inside one lot.
    text = "Title: Test\nOfficial name: Amt\nLot: LOT-0001\nEstimated value excluding VAT: 500 000,00 EUR\n" \
           "Framework agreement: No framework agreement"
    out = extract_rules(text)
    assert out["amount_value"] is None and out["needs_manual_review"] is True


def test_llm_output_with_unverifiable_values_is_flagged():
    text = text_of("804251-2026")
    good = {**extract_rules(text), "evidence": "Value of all contracts awarded in this notice: 138 100,00 EUR"}
    assert check_llm_output(dict(good), text)["needs_manual_review"] is False
    bad = check_llm_output({**good, "amount_value": 999000.0, "buyer": None}, text)  # quote no longer matches
    assert bad["needs_manual_review"] is True
    assert "does not state this amount" in bad["review_reason"] and "missing buyer" in bad["review_reason"]
    invented = check_llm_output({**good, "evidence": "Value of all contracts awarded in this notice: 138 100,00 EUR!"}, text)
    assert "not found in notice text" in invented["review_reason"]


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
