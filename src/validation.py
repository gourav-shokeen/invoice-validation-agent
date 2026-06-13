from __future__ import annotations

from typing import Any, Optional

# one-cent rounding tolerance
TOLERANCE = 0.01

REQUIRED_FIELDS = ("vendor", "invoice_number", "invoice_date", "total")


def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def validate_invoice(extracted: Optional[dict]) -> list[str]:
    errors: list[str] = []

    if not extracted:
        return ["No invoice data was extracted."]

    for field in REQUIRED_FIELDS:
        if _is_blank(extracted.get(field)):
            errors.append(f"Required field '{field}' is missing or empty.")

    if _is_blank(extracted.get("currency")):
        errors.append("Currency is missing or empty.")

    subtotal = _as_float(extracted.get("subtotal"))
    tax_amount = _as_float(extracted.get("tax_amount"))
    total = _as_float(extracted.get("total"))
    tax_rate = _as_float(extracted.get("tax_rate"))
    line_items = extracted.get("line_items") or []

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

    if subtotal is not None and tax_amount is not None and total is not None:
        if abs((subtotal + tax_amount) - total) > TOLERANCE:
            errors.append(
                f"Subtotal {subtotal:.2f} + tax {tax_amount:.2f} = "
                f"{subtotal + tax_amount:.2f}, which does not match the stated "
                f"total {total:.2f}."
            )

    if tax_rate is not None and subtotal is not None and tax_amount is not None:
        expected_tax = subtotal * tax_rate
        if abs(expected_tax - tax_amount) > TOLERANCE:
            errors.append(
                f"Tax amount {tax_amount:.2f} does not match subtotal "
                f"{subtotal:.2f} * tax_rate {tax_rate:.4g} = {expected_tax:.2f}."
            )

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
