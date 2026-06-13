"""Unit tests for the deterministic invoice validator.

These exercise `validate_invoice` only — no API, no LLM, USE_MOCK_LLM not even
needed. The validator imports only the standard library.
"""
from __future__ import annotations

import copy

from src.validation import TOLERANCE, validate_invoice


def consistent_invoice() -> dict:
    """A fully consistent invoice (19% German VAT) that must pass with zero errors."""
    return {
        "vendor": "ACME Cloud Solutions GmbH",
        "invoice_number": "INV-2025-0042",
        "invoice_date": "2025-03-14",
        "currency": "EUR",
        "line_items": [
            {"description": "Cloud Hosting", "quantity": 1, "unit_price": 1200.0, "line_total": 1200.0},
            {"description": "Support", "quantity": 10, "unit_price": 85.0, "line_total": 850.0},
            {"description": "Migration", "quantity": 1, "unit_price": 450.0, "line_total": 450.0},
        ],
        "subtotal": 2500.0,
        "tax_rate": 0.19,
        "tax_amount": 475.0,
        "total": 2975.0,
    }


def broken_invoice() -> dict:
    """Printed totals are internally inconsistent: 100 + 19 != 150."""
    return {
        "vendor": "Nordwind Software UG",
        "invoice_number": "INV-2025-0099",
        "invoice_date": "2025-04-02",
        "currency": "EUR",
        "line_items": [
            {"description": "Consulting Services", "quantity": 2, "unit_price": 30.0, "line_total": 60.0},
            {"description": "Software License Fee", "quantity": 1, "unit_price": 40.0, "line_total": 40.0},
        ],
        "subtotal": 100.0,
        "tax_rate": 0.19,
        "tax_amount": 19.0,
        "total": 150.0,
    }


def test_consistent_invoice_has_no_errors():
    assert validate_invoice(consistent_invoice()) == []


def test_broken_invoice_flags_total_mismatch():
    errors = validate_invoice(broken_invoice())
    assert len(errors) == 1
    assert "does not match the stated" in errors[0]
    assert "150.00" in errors[0]


def test_within_tolerance_passes():
    inv = consistent_invoice()
    # Nudge the total by less than one cent — must still pass.
    inv["total"] = inv["total"] + (TOLERANCE / 2)
    assert validate_invoice(inv) == []


def test_missing_required_fields():
    inv = consistent_invoice()
    inv["vendor"] = ""
    del inv["invoice_number"]
    errors = validate_invoice(inv)
    assert any("vendor" in e for e in errors)
    assert any("invoice_number" in e for e in errors)


def test_empty_currency_flagged():
    inv = consistent_invoice()
    inv["currency"] = "   "
    errors = validate_invoice(inv)
    assert any("currency" in e.lower() for e in errors)


def test_line_items_do_not_sum_to_subtotal():
    inv = consistent_invoice()
    # Line items now sum to 2299, but subtotal/tax/total stay consistent at 2500/475/2975,
    # so only the line-sum check should fire.
    inv["line_items"][0]["line_total"] = 999.0
    errors = validate_invoice(inv)
    assert len(errors) == 1
    assert "Line items sum to" in errors[0]


def test_tax_rate_mismatch():
    inv = consistent_invoice()
    # Keep subtotal+tax == total so only the tax-rate check fails.
    inv["subtotal"] = 100.0
    inv["tax_amount"] = 25.0
    inv["total"] = 125.0
    inv["tax_rate"] = 0.19
    inv["line_items"] = [
        {"description": "x", "quantity": 1, "unit_price": 100.0, "line_total": 100.0}
    ]
    errors = validate_invoice(inv)
    assert any("does not match subtotal" in e for e in errors)


def test_negative_amount_flagged():
    inv = consistent_invoice()
    inv["line_items"][0]["unit_price"] = -1200.0
    errors = validate_invoice(inv)
    assert any("negative" in e.lower() for e in errors)


def test_none_returns_error():
    assert validate_invoice(None) == ["No invoice data was extracted."]
    assert validate_invoice({}) == ["No invoice data was extracted."]


def test_multiple_errors_accumulate():
    inv = {
        "vendor": "",
        "invoice_number": "",
        "invoice_date": "",
        "currency": "",
        "line_items": [],
        "subtotal": -5.0,
        "tax_rate": None,
        "tax_amount": 0.0,
        "total": -10.0,
    }
    errors = validate_invoice(inv)
    # At least: vendor, invoice_number, invoice_date, total, currency, 2 negatives.
    assert len(errors) >= 6


def test_validator_does_not_mutate_input():
    inv = consistent_invoice()
    snapshot = copy.deepcopy(inv)
    validate_invoice(inv)
    assert inv == snapshot
