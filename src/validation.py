"""Deterministic invoice validation — no LLM, no network, no environment.

This module is the heart of the EN 16931 / ZUGFeRD-style consistency checks. It
validates the arithmetic and completeness of an extracted invoice exactly as it
was transcribed from the source document. It never recomputes or "repairs"
figures: a document whose printed totals do not add up is a *finding*, not a
value to be silently corrected.

It imports only the standard library so the validator (and its unit tests) stay
free of any LLM or API dependency.
"""
from __future__ import annotations

from typing import Any, Optional

# Absolute tolerance (in currency minor units) for monetary comparisons.
# 0.01 == one cent, matching the precision printed on most invoices.
TOLERANCE = 0.01

REQUIRED_FIELDS = ("vendor", "invoice_number", "invoice_date", "total")


def _as_float(value: Any) -> Optional[float]:
    """Coerce a value to float, returning None if missing/uncoercible."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_blank(value: Any) -> bool:
    """True if a value is None or an empty/whitespace-only string."""
    return value is None or (isinstance(value, str) and value.strip() == "")


def validate_invoice(extracted: Optional[dict]) -> list[str]:
    """Return human-readable validation errors for an extracted invoice.

    An empty list means the invoice is complete and internally consistent.

    Checks performed:
      1. Required fields present and non-empty (vendor, invoice_number,
         invoice_date, total).
      2. Sum of line_item totals matches the stated subtotal (+/- TOLERANCE).
      3. subtotal + tax_amount matches the stated total (+/- TOLERANCE).
      4. If a tax_rate is given, tax_amount matches subtotal * tax_rate.
      5. Currency is present and non-empty.
      6. No monetary amount or quantity is negative.
    """
    errors: list[str] = []

    if not extracted:
        return ["No invoice data was extracted."]

    # 1. Required fields ---------------------------------------------------
    for field in REQUIRED_FIELDS:
        if _is_blank(extracted.get(field)):
            errors.append(f"Required field '{field}' is missing or empty.")

    # 5. Currency ----------------------------------------------------------
    if _is_blank(extracted.get("currency")):
        errors.append("Currency is missing or empty.")

    subtotal = _as_float(extracted.get("subtotal"))
    tax_amount = _as_float(extracted.get("tax_amount"))
    total = _as_float(extracted.get("total"))
    tax_rate = _as_float(extracted.get("tax_rate"))
    line_items = extracted.get("line_items") or []

    # 2. Line items sum to subtotal ---------------------------------------
    if subtotal is not None and line_items:
        line_sum = 0.0
        for idx, item in enumerate(line_items, start=1):
            line_total = _as_float(item.get("line_total")) if isinstance(item, dict) else None
            if line_total is None:
                errors.append(f"Line item {idx} is missing a numeric line_total.")
            else:
                line_sum += line_total
        if abs(line_sum - subtotal) > TOLERANCE:
            errors.append(
                f"Line items sum to {line_sum:.2f} but the stated subtotal is "
                f"{subtotal:.2f} (difference {abs(line_sum - subtotal):.2f})."
            )

    # 3. subtotal + tax_amount == total -----------------------------------
    if subtotal is not None and tax_amount is not None and total is not None:
        if abs((subtotal + tax_amount) - total) > TOLERANCE:
            errors.append(
                f"Subtotal {subtotal:.2f} + tax {tax_amount:.2f} = "
                f"{subtotal + tax_amount:.2f}, which does not match the stated "
                f"total {total:.2f}."
            )

    # 4. tax_amount == subtotal * tax_rate --------------------------------
    if tax_rate is not None and subtotal is not None and tax_amount is not None:
        expected_tax = subtotal * tax_rate
        if abs(expected_tax - tax_amount) > TOLERANCE:
            errors.append(
                f"Tax amount {tax_amount:.2f} does not match subtotal "
                f"{subtotal:.2f} * tax_rate {tax_rate:.4g} = {expected_tax:.2f}."
            )

    # 6. No negative amounts ----------------------------------------------
    for field in ("subtotal", "tax_amount", "total"):
        val = _as_float(extracted.get(field))
        if val is not None and val < 0:
            errors.append(f"Field '{field}' is negative ({val:.2f}).")
    for idx, item in enumerate(line_items, start=1):
        if not isinstance(item, dict):
            continue
        for field in ("quantity", "unit_price", "line_total"):
            val = _as_float(item.get(field))
            if val is not None and val < 0:
                errors.append(f"Line item {idx} has a negative {field} ({val:.2f}).")

    return errors
