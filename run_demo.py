"""End-to-end demo: TED notices -> text -> structured records -> validation.

    python3 run_demo.py            # offline: rebuild output from stored raw data (no network, no key)
    python3 run_demo.py --live     # re-fetch notices from TED into data/raw/ first
    python3 run_demo.py --llm      # use Claude instead of the rule-based extractor

Outputs: data/sample_output.csv / .json (rules) or data/llm_output.* (--llm).
"""

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import ted_api
from extract import LLM_MODEL, extract_llm, extract_rules
from parse_notice import excerpt, html_to_text
from validate import validate_records

DATA = Path(__file__).parent / "data"
RAW = DATA / "raw"

COLUMNS = [
    "notice_id", "source_url", "fetched_at_utc", "raw_html_path", "raw_text_excerpt",
    "publication_date", "country", "buyer", "title", "amount_value", "currency",
    "amount_kind", "is_framework_agreement", "is_framework_ceiling",
    "needs_manual_review", "review_reason", "extraction_method",
    "validation_status", "validation_notes",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_live(limit: int) -> None:
    """Store the untouched API response and notice pages, plus when/where they came from."""
    (RAW / "html").mkdir(parents=True, exist_ok=True)
    searches = []
    for query in (ted_api.DEFAULT_QUERY, ted_api.EDGE_CASE_QUERY):
        searches.append({"fetched_at_utc": _utc_now(), "endpoint": ted_api.SEARCH_URL,
                         "query": query, "response": ted_api.search_notices(query, limit)})
    (RAW / "search_response.json").write_text(json.dumps(searches, indent=2, ensure_ascii=False))

    manifest = {}
    for notice in _notices(searches):
        nid = notice["publication-number"]
        path = RAW / "html" / f"{nid}.html"
        url = ted_api.NOTICE_HTML_URL.format(notice_id=nid)
        manifest[nid] = {"source_url": url, "fetched_at_utc": _utc_now(),
                         "raw_html_path": str(path.relative_to(DATA.parent))}
        path.write_text(ted_api.fetch_notice_html(nid), encoding="utf-8")
        time.sleep(2)  # be polite: TED rate-limits fast clients (HTTP 429)
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2))


def _notices(searches: list[dict]) -> list[dict]:
    """All notices from all stored searches, first occurrence wins."""
    seen = {}
    for search in searches:
        for notice in search["response"]["notices"]:
            seen.setdefault(notice["publication-number"], notice)
    return list(seen.values())


def build_record(notice: dict, prov: dict, text: str, ext: dict, method: str) -> dict:
    # Cross-check: structured API flag vs. what was extracted from the text.
    api_framework = any(v != "none" for v in notice.get("framework-agreement-lot", []))
    if api_framework and ext["is_framework_agreement"] is False:
        ext["needs_manual_review"] = True
        ext["review_reason"] = "; ".join(filter(None, [ext["review_reason"], "API flags framework, text does not"]))

    fa, amount = ext["is_framework_agreement"], ext["amount_value"]
    # Is the amount a framework ceiling (not real spending)? None = can't tell yet.
    ceiling = False if amount is None else fa
    return {
        "notice_id": notice["publication-number"],
        **prov,
        "raw_text_excerpt": ext["evidence"] or excerpt(text, r"Description: "),
        "publication_date": notice["publication-date"][:10],  # API gives '2026-11-20+01:00'
        "country": (notice.get("buyer-country") or [None])[0],
        "buyer": ext["buyer"],
        "title": ext["title"],
        "amount_value": amount,
        "currency": ext["currency"],
        "amount_kind": ext["amount_kind"],
        "is_framework_agreement": fa,
        "is_framework_ceiling": ceiling,
        "needs_manual_review": ext["needs_manual_review"],
        "review_reason": ext["review_reason"],
        "extraction_method": method,
    }


def build_all(extractor, method: str) -> list[dict]:
    """Rebuild every record from the stored raw files (no network)."""
    searches = json.loads((RAW / "search_response.json").read_text())
    manifest = json.loads((RAW / "manifest.json").read_text())
    records = []
    for notice in _notices(searches):
        prov = manifest[notice["publication-number"]]
        text = html_to_text((DATA.parent / prov["raw_html_path"]).read_text(encoding="utf-8"))
        records.append(build_record(notice, prov, text, extractor(text), method))
    return validate_records(records)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="re-fetch from TED first")
    ap.add_argument("--llm", action="store_true", help="extract with Claude (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    if args.live:
        fetch_live(args.limit)

    records = build_all(*((extract_llm, f"llm:{LLM_MODEL}") if args.llm else (extract_rules, "rules")))

    stem = "llm_output" if args.llm else "sample_output"
    (DATA / f"{stem}.json").write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    with open(DATA / f"{stem}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(records)

    for r in records:
        amount = f"{r['amount_value']:,.2f} {r['currency']}" if r["amount_value"] is not None else "null"
        print(f"{r['notice_id']:<12} {r['validation_status']:<12} {amount:>18}  {(r['title'] or '')[:60]}")
    print(f"\nWrote data/{stem}.csv and data/{stem}.json ({len(records)} records)")


if __name__ == "__main__":
    main()
