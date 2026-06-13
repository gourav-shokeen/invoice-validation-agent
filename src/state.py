from __future__ import annotations

from typing import Optional, TypedDict

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str = Field(description="The line item description, verbatim.")
    quantity: float = Field(description="Quantity billed, as printed.")
    unit_price: float = Field(description="Price per unit, as printed.")
    line_total: float = Field(description="Total for this line, as printed.")


class InvoiceData(BaseModel):
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
    raw_text: str
    extracted: Optional[dict]
    # overwritten each validate pass, not accumulated
    validation_errors: list[str]
    status: str
    attempts: int
    summary: str
