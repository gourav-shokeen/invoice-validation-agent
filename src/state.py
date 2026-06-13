"""State and schemas for the Invoice Validation Agent.

`AgentState` is the TypedDict that flows through the LangGraph state machine.
`InvoiceData` / `LineItem` are the Pydantic v2 schemas the LLM is asked to fill
via `.with_structured_output(...)`.
"""
from __future__ import annotations

from typing import Optional, TypedDict

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    """A single billed line on the invoice, transcribed exactly as printed."""

    description: str = Field(description="The line item description, verbatim.")
    quantity: float = Field(description="Quantity billed, as printed.")
    unit_price: float = Field(description="Price per unit, as printed.")
    line_total: float = Field(description="Total for this line, as printed.")


class InvoiceData(BaseModel):
    """Structured invoice fields extracted from the raw document text.

    Values must be transcribed exactly as printed — see the extraction prompt.
    Figures are never recomputed here; downstream validation checks whether the
    document's own stated figures are internally consistent.
    """

    vendor: str = Field(description="Name of the issuing vendor/supplier.")
    invoice_number: str = Field(description="The invoice number/identifier.")
    invoice_date: str = Field(description="The invoice date, as printed.")
    currency: str = Field(description="ISO currency code as printed, e.g. EUR.")
    line_items: list[LineItem] = Field(
        default_factory=list, description="All billed line items."
    )
    subtotal: float = Field(description="Net subtotal as stated on the document.")
    tax_rate: Optional[float] = Field(
        default=None,
        description="Tax rate as a decimal fraction (0.19 for 19%); null if absent.",
    )
    tax_amount: float = Field(description="Tax amount as stated on the document.")
    total: float = Field(description="Gross total as stated on the document.")


class AgentState(TypedDict):
    """The mutable state carried through the graph.

    Fields without a reducer are overwritten by each node that returns them;
    `validation_errors` is intentionally overwritten on every `validate` pass so
    a retry is judged on its own merits, not an accumulation of stale errors.
    """

    raw_text: str
    extracted: Optional[dict]
    validation_errors: list[str]
    status: str
    attempts: int
    summary: str
