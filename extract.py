"""Extract structured fields from notice text into ONE fixed JSON schema.

Two interchangeable extractors fill the same schema:
  * extract_rules(text) - deterministic regex fallback, no API key, used by default
  * extract_llm(text)   - Claude with structured outputs (needs ANTHROPIC_API_KEY)

Both outputs go through check_schema() and apply_guards(), so an LLM answer is
treated like any other untrusted input. Rule: never guess - a missing or
ambiguous value becomes null + needs_manual_review=True with a reason.
"""

import json
import re


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title", "buyer", "amount_value", "currency", "amount_kind",
        "is_framework_agreement", "needs_manual_review", "review_reason", "evidence",
    ],
    "properties": {
        "title": _nullable({"type": "string"}),
        "buyer": _nullable({"type": "string"}),
        "amount_value": _nullable({"type": "number"}),
        "currency": _nullable({"type": "string"}),
        "amount_kind": _nullable({"type": "string", "enum": ["awarded", "estimated", "framework_maximum"]}),
        "is_framework_agreement": _nullable({"type": "boolean"}),
        "needs_manual_review": {"type": "boolean"},
        "review_reason": _nullable({"type": "string"}),
        "evidence": {"type": "string"},
    },
}

_PY_TYPES = {"string": str, "number": (int, float), "boolean": bool, "null": type(None)}


def _matches(value, schema: dict) -> bool:
    if "anyOf" in schema:
        return any(_matches(value, s) for s in schema["anyOf"])
    if schema["type"] == "number" and isinstance(value, bool):
        return False  # bool is a subclass of int in Python
    if not isinstance(value, _PY_TYPES[schema["type"]]):
        return False
    return "enum" not in schema or value in schema["enum"]


def check_schema(data: dict) -> list[str]:
    """Minimal validator for SCHEMA (keeps the demo dependency-free)."""
    errors = []
    missing = set(SCHEMA["required"]) - set(data)
    extra = set(data) - set(SCHEMA["properties"])
    errors += [f"missing field: {k}" for k in sorted(missing)]
    errors += [f"unexpected field: {k}" for k in sorted(extra)]
    for key, sub in SCHEMA["properties"].items():
        if key in data and not _matches(data[key], sub):
            errors.append(f"bad type for {key}: {data[key]!r}")
    return errors


def _review(out: dict, reason: str) -> None:
    out["needs_manual_review"] = True
    out["review_reason"] = "; ".join(filter(None, [out["review_reason"], reason]))


def apply_guards(out: dict) -> dict:
    """Deterministic post-checks applied to EVERY extractor (rules or LLM)."""
    amount = out["amount_value"]
    if amount is not None and amount <= 1:
        # Real TED pattern: buyers enter 1,00 EUR when they do not want to publish a value.
        _review(out, f"placeholder amount {amount:g} in source -> set to null")
        out["amount_value"] = None
    if out["amount_value"] is None:
        out["currency"] = out["amount_kind"] = None
        if not out["needs_manual_review"]:
            _review(out, "no amount found")
    if out["is_framework_agreement"] is None and "framework" not in (out["review_reason"] or ""):
        _review(out, "framework status unclear")
    return out


# ---------------------------------------------------------------- rules ----

_AMOUNT = r"(\d[\d .\u00a0]*,\d{2}) ([A-Z]{3})"  # EU number format, same line only
# Order matters: an awarded value is better evidence than an estimate.
_AMOUNT_LABELS = [
    ("awarded", r"Value of all contracts awarded in this notice: "),
    ("framework_maximum", r"Maximum value of the framework agreements?(?: in this notice)?: "),
    ("estimated", r"Estimated value excluding VAT: "),
]
_FRAMEWORK_WORDS = r"Rahmenvereinbarung|Rahmenvertrag|framework agreement|^RV\b"


def _parse_number(raw: str) -> float:
    """'138 100,00' / '1.300.000,00' (EU format) -> 138100.0 / 1300000.0"""
    return float(re.sub(r"[ .\u00a0]", "", raw).replace(",", "."))


def _first(pattern: str, text: str):
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


def extract_rules(text: str) -> dict:
    out = {
        "title": _first(r"Title: ([^\n]+)", text),
        "buyer": _first(r"Official name: ([^\n]+)", text),  # first org = buyer (section 1)
        "amount_value": None, "currency": None, "amount_kind": None,
        "is_framework_agreement": None, "needs_manual_review": False,
        "review_reason": None, "evidence": "",
    }

    for kind, label in _AMOUNT_LABELS:
        m = re.search(label + _AMOUNT, text)
        if m:
            out.update(amount_value=_parse_number(m.group(1)), currency=m.group(2), amount_kind=kind)
            out["evidence"] = m.group(0)
            break
        if re.search(label + "unpublished", text):
            _review(out, f"{kind} value marked 'unpublished'")

    # Structured field ("Framework agreement: ...") vs. free-text signals.
    techniques = re.findall(r"Framework agreement: (No framework agreement|Framework agreement[^\n]*)", text)
    structured = None if not techniques else any(t != "No framework agreement" for t in techniques)
    free_text = "\n".join(re.findall(r"(?:Title|Description): ([^\n]+)", text))
    mentioned = re.search(_FRAMEWORK_WORDS, free_text, flags=re.IGNORECASE | re.MULTILINE)

    if structured is False and mentioned:
        _review(out, f"structured field says no framework, but text mentions '{mentioned.group(0)}'")
    else:
        out["is_framework_agreement"] = structured if structured is not None else (True if mentioned else None)
    if techniques:
        out["evidence"] = (out["evidence"] + " | Framework agreement: " + techniques[0]).strip(" |")
    return apply_guards(out)


# ------------------------------------------------------------------ LLM ----

LLM_MODEL = "claude-opus-5-5"
LLM_PROMPT = """You extract fields from one EU public procurement notice (TED).
Rules:
- Copy values from the text; never infer or guess. If a value is absent, use null.
- amount_value: the total contract value excluding VAT as a number (prefer the
  awarded value, then a framework maximum, then the estimate). Values of 1 or
  less are placeholders: set null.
- is_framework_agreement: true/false only if the text states it; if the
  structured field and the description contradict each other, use null.
- If anything is null or ambiguous, set needs_manual_review=true and explain in
  review_reason. evidence: a short verbatim quote supporting the amount.

Notice text:
"""


def extract_llm(text: str) -> dict:
    """Same schema, filled by Claude. Optional: needs `pip install anthropic`."""
    import anthropic  # imported lazily so the default demo needs no packages

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=LLM_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # retry on a fallback model if the request is declined
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": LLM_PROMPT + text}],
    )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"LLM extraction stopped: {response.stop_reason}")
    data = json.loads(next(b.text for b in response.content if b.type == "text"))
    errors = check_schema(data)
    if errors:
        raise ValueError(f"LLM output violates schema: {errors}")
    return apply_guards(data)
