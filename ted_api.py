"""Fetch public procurement notices from TED (Tenders Electronic Daily).

Uses only the official, anonymous TED Search API v3 and the public notice pages.
Docs: https://docs.ted.europa.eu/api/latest/search.html
"""

import json
import time
import urllib.error
import urllib.request

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
NOTICE_HTML_URL = "https://ted.europa.eu/en/notice/{notice_id}/html"

# CPV 35000000 ("Security, fire-fighting, police and defence equipment") also
# contains fire engines and police gear. To stay close to *military* procurement
# we restrict to its defence divisions: 353 weapons/ammunition, 354 military
# vehicles, 355 warships, 356 military aircraft/missiles, 357 military
# electronic systems. TED matches CPV codes hierarchically (sub-codes included).
DEFAULT_QUERY = (
    "classification-cpv IN (35300000 35400000 35500000 35600000 35700000) "
    "AND buyer-country=DEU SORT BY publication-date DESC"
)

# Hand-picked older notices that illustrate edge cases the latest 10 may lack:
# a framework with a published 150 M EUR ceiling, an awarded framework, and a
# framework ("RV") published with a 1,00 EUR placeholder value.
EDGE_CASE_QUERY = "publication-number IN (672950-2026 623890-2026 785099-2026)"

FIELDS = [
    "publication-number",
    "publication-date",
    "notice-type",
    "buyer-country",
    "classification-cpv",
    "framework-agreement-lot",
]

USER_AGENT = "ted-procurement-demo/0.1 (research demo; python urllib)"


def _request(req: urllib.request.Request, retries: int = 3) -> bytes:
    """HTTP request with a polite back-off; TED answers 429 when hit too fast."""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            if err.code != 429 or attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def search_notices(query: str = DEFAULT_QUERY, limit: int = 10) -> dict:
    """Return the raw JSON response of the TED search API (unmodified)."""
    body = json.dumps({"query": query, "fields": FIELDS, "page": 1, "limit": limit}).encode()
    req = urllib.request.Request(
        SEARCH_URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    return json.loads(_request(req))


def fetch_notice_html(notice_id: str) -> str:
    """Return the public HTML rendering of one notice (English labels)."""
    req = urllib.request.Request(
        NOTICE_HTML_URL.format(notice_id=notice_id), headers={"User-Agent": USER_AGENT}
    )
    return _request(req).decode("utf-8")
