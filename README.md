# ted-procurement-demo

**A compact demonstration project**, not a research dataset. It shows, end to end and
with real public data, how I would collect defence procurement notices, turn
unstructured notice text into a fixed schema, keep a source trail for every value, and
flag what a human has to check. About 500 lines of Python plus 120 lines of tests.

```
TED Search API (JSON) ──► notice HTML pages ──► plain text ──► extractor ──► guards ──► validate ──► CSV / JSON
        └── stored unmodified in data/raw/ with fetch time + URL (provenance) ──┘   (rules or Claude)
```

## Quickstart (Python 3.10+, no packages needed)

```bash
python3 run_demo.py
```

This rebuilds `data/sample_output.csv` / `.json` from the stored raw files in a second,
offline, without an API key. Other modes:

| Command | What it does |
|---|---|
| `python3 run_demo.py --live` | re-fetches the notices from TED into `data/raw/` (network, ~30 s) |
| `python3 run_demo.py --llm` | extracts with Claude instead of regex rules (`pip install anthropic`, `ANTHROPIC_API_KEY`) → `data/llm_output.*` |
| `python3 validate.py data/sample_output.json` | runs the plausibility checks only |
| `pip install pytest && python3 -m pytest` | 25 tests, all on the stored real notices |

## Data source

* **TED Search API v3** (`api.ted.europa.eu/v3/notices/search`), anonymous, official EU source.
* Query: CPV division **35** (`35000000`, security & defence equipment) restricted to its
  defence groups 353–357 (weapons/ammunition, military vehicles, warships, military
  aircraft/missiles, military electronics), buyer country Germany, newest first, 10 notices.
  The plain `35000000` code is dominated by fire engines and police equipment.
* Plus 3 hand-picked notices (`EDGE_CASE_QUERY` in `ted_api.py`) that illustrate edge
  cases: a framework with a published ceiling, an awarded framework, and a 1,00 EUR placeholder.
* For each notice the public HTML page (`ted.europa.eu/en/notice/<id>/html`) is parsed
  with Python's `html.parser`. Labels are English; descriptions stay in the original German.
* Snapshot in this repo: fetched 2026-11-22 (UTC), 13 notices.

## Output schema (one row per notice)

| Field | Meaning |
|---|---|
| `notice_id`, `source_url`, `fetched_at_utc`, `raw_html_path` | provenance: where and when the value came from, and the untouched raw file |
| `raw_text_excerpt` | verbatim text the amount / framework status was taken from |
| `publication_date`, `country` | from the structured API response |
| `buyer`, `title`, `amount_value`, `currency`, `amount_kind` | extracted from the notice text; `amount_kind` ∈ awarded / framework_maximum / estimated |
| `is_framework_agreement`, `is_framework_ceiling` | `is_framework_ceiling = true` means the amount is a maximum, **not** realised spending |
| `needs_manual_review`, `review_reason` | set instead of guessing whenever a value is missing, a placeholder, or contradictory |
| `extraction_method` | `rules` or `llm:<model>` |
| `validation_status`, `validation_notes` | `ok` / `needs_review` / `error` from `validate.py` |

## Sample output (`data/sample_output.csv`, abridged)

| notice_id | title (truncated) | amount | framework | status |
|---|---|---:|---|---|
| 804251-2026 | Fertigung und Integration von Raketenspitzen | 138,100 EUR | False | ok |
| 799870-2026 | Rahmenvereinbarung über die Lieferung von Tra… | null | True | needs_review |
| 796992-2026 | Munition 9x19mm SWDD | null | True | needs_review |
| 798280-2026 | Rahmenvereinbarung über die Lieferung von mob… | null | null | needs_review |
| 798868-2026 | Beschaffung von Werkzeugsätzen IED Spezialkrä… | 847,719 EUR | False | ok |
| 623890-2026 | 57MM TARGET PRACTICE (TP) | 16,589,412 EUR | True | needs_review |
| 672950-2026 | Herstellung von Basishelikoptern nebst Ausrüs… | 150,000,000 EUR | True | needs_review |
| 785099-2026 | RV IRIS Radar System mit Zubehör | null | null | needs_review |

Only 2 of 13 notices give an unambiguous contract value. Most German defence notices
publish no value, or mark it "unpublished". That is the main finding of this small sample.

## A checked edge case: notice 785099-2026

The [notice](https://ted.europa.eu/en/notice/785099-2026/html) (Bavarian police, drone-detection radar) is a typical trap:

* the title starts with **"RV"** (*Rahmenvertrag*) and the description says
  *"Vergabe einer Rahmenvereinbarung"*, but the structured field says **"No framework agreement"**;
* every value field (estimated, tender, awarded) reads **1,00 EUR**, a placeholder for "not disclosed".

A naive scraper would record a 1 EUR non-framework contract. The pipeline outputs:

```json
"amount_value": null,
"currency": null,
"is_framework_agreement": null,
"needs_manual_review": true,
"review_reason": "structured field says no framework, but text mentions 'RV'; placeholder amount 1 in source -> set to null",
"raw_text_excerpt": "Value of all contracts awarded in this notice: 1,00 EUR | Framework agreement: No framework agreement"
```

I checked this by hand against the notice page. It is covered by
`test_placeholder_and_contradiction_become_null_with_review`.

## How the extraction works

* `extract.py` defines one JSON Schema (`SCHEMA`). Two extractors fill it:
  * `extract_rules`: regex on the TED labels, deterministic, the default;
  * `extract_llm`: Claude (`claude-opus-5-5`) with **structured outputs** constrained to
    the same schema. The prompt says to copy values, never infer them, and to use null otherwise.
* Both outputs then go through the same checks. The LLM answer is treated as untrusted input:
  * `check_schema()` validates types, required fields and enums;
  * `apply_guards()` turns amounts ≤ 1 into null and flags every null or unclear field for review.
* `run_demo.py` cross-checks the API's structured framework flag against the extracted one.
* `validate.py` checks the ISO currency, amount > 0 or explicit null (null must be flagged),
  ISO dates, a UTC fetch timestamp, a TED source URL, duplicate `notice_id`s, and that a
  framework ceiling is never reported as plain spending.

## Limitations & manual verification

* **Small, hand-checked sample** (13 notices, one country, one CPV division). The regexes
  rely on TED's English HTML labels (eForms layout, 2026) and will need updating if the layout changes.
* **HTML instead of PDF.** TED's PDFs are renderings of the same eForms notice, so the demo
  reads the Search API and the HTML page, which keep label/value structure and avoid
  layout-dependent PDF text extraction. For PDF-only sources (e.g. national portals), the same
  `check_schema()` / `apply_guards()` step would run on the text after PDF text extraction.
* **Values are notice-level.** Lot-level splits, options, VAT and currency conversion are not handled.
* **Defence notices often hide values**, and contracts exempted under Art. 346 TFEU
  never appear on TED at all, so TED covers only part of military procurement.
* **The LLM mode is optional and was not used for the stored sample.** Its output passes
  the same schema and guard checks, but it still needs spot checks against `raw_text_excerpt` and `source_url`.
* Every `needs_review` row is meant for a person to check against the linked notice. The
  pipeline makes those rows explicit instead of filling the gaps.

## Files

```
ted_api.py       TED search + notice download (urllib, polite retry on HTTP 429)
parse_notice.py  HTML -> "Label: value" text (html.parser)
extract.py       JSON schema, rule-based and Claude extractors, guards
validate.py      plausibility checks (also a CLI)
run_demo.py      pipeline: fetch (optional) -> extract -> validate -> CSV/JSON
data/raw/        untouched API responses, notice HTML, manifest with fetch times
tests/           pytest, runs on the stored real notices
LICENSE          MIT
```
