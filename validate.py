"""Plausibility checks for extracted procurement records.

Usage:  python3 validate.py data/sample_output.json
Sets `validation_status` (ok | needs_review | error) and `validation_notes`
on every record. Exit code 1 if any record has status 'error'.
"""

import json
import math
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta

# shortcut: currencies seen in EU/EEA procurement only; use a full ISO 4217 list for global sources.
ISO_CURRENCIES = {"EUR", "BGN", "CZK", "DKK", "HUF", "PLN", "RON", "SEK", "NOK", "ISK", "CHF", "GBP", "USD"}
NOTICE_ID = re.compile(r"^\d{1,8}-\d{4}$")  # TED publication number, e.g. 785099-2026


def _is_iso_date(value) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def _is_utc_timestamp(value) -> bool:
    try:
        return datetime.fromisoformat(value).utcoffset() == timedelta(0)
    except (TypeError, ValueError):
        return False


def check_record(rec: dict) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one record."""
    errors, warnings = [], []

    if not NOTICE_ID.match(str(rec.get("notice_id", ""))):
        errors.append("invalid notice_id")
    url = str(rec.get("source_url") or "")
    if not url.startswith("https://ted.europa.eu/"):
        errors.append("missing or non-TED source_url")
    elif f"/{rec.get('notice_id')}/" not in url:
        errors.append("source_url points to a different notice")
    if not _is_iso_date(rec.get("publication_date")):
        errors.append("publication_date is not an ISO date (YYYY-MM-DD)")
    if not _is_utc_timestamp(rec.get("fetched_at_utc")):
        errors.append("fetched_at_utc is not an ISO UTC timestamp")

    amount, currency = rec.get("amount_value"), rec.get("currency")
    if amount is None:
        if currency is not None:
            errors.append("currency set without amount")
        if not rec.get("needs_manual_review"):
            errors.append("amount is null but record is not flagged for review")
    else:
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 0 < amount < math.inf:
            errors.append(f"amount must be a finite number > 0 or null, got {amount!r}")
        if currency not in ISO_CURRENCIES:
            errors.append(f"invalid currency {currency!r}")

    # Framework maximum: the published value is a ceiling, not actual spending.
    if bool(rec.get("is_framework_ceiling")) != (rec.get("amount_kind") == "framework_maximum" and amount is not None):
        errors.append("is_framework_ceiling does not match amount_kind")
    elif rec.get("is_framework_ceiling"):
        warnings.append("amount is a framework ceiling, not realised spending")

    if rec.get("needs_manual_review"):
        warnings.append(f"manual review: {rec.get('review_reason') or 'no reason given'}")
    return errors, warnings


def validate_records(records: list[dict]) -> list[dict]:
    counts = Counter(r.get("notice_id") for r in records)
    for rec in records:
        errors, warnings = check_record(rec)
        if counts[rec.get("notice_id")] > 1:
            errors.append("duplicate notice_id")
        rec["validation_status"] = "error" if errors else ("needs_review" if warnings else "ok")
        rec["validation_notes"] = "; ".join(errors + warnings)
    return records


def main(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        records = validate_records(json.load(f))
    for r in records:
        print(f"{r['notice_id']:<14} {r['validation_status']:<13} {r['validation_notes']}")
    summary = Counter(r["validation_status"] for r in records)
    print("\nSummary:", dict(summary))
    return 1 if summary["error"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/sample_output.json"))
