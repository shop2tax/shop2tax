"""Pydantic schemas for document extraction results."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class ExtractionLineItem(BaseModel):
    """A single line item extracted from a document."""

    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    tax_rate: Decimal | None = None


class ExtractionResult(BaseModel):
    """Structured data extracted from an invoice document.

    Source indicates extraction method:
    - "zugferd": Parsed from embedded ZUGFeRD/Factur-X XML (free, deterministic)
    - "gemini", "openai", "anthropic": Vision-LLM extraction
    - "manual": No extraction possible, user must fill manually
    """

    source: str  # "zugferd", "gemini", "openai", "anthropic", "manual"
    receipt_number: str | None = None
    date: str | None = None  # YYYY-MM-DD
    delivery_date: str | None = None
    due_date: str | None = None
    billing_period: str | None = None
    counterparty: str | None = None
    counterparty_address: str | None = None
    tax_number: str | None = None
    vat_id: str | None = None
    currency: str = "EUR"
    line_items: list[ExtractionLineItem] = []
    total_net: Decimal | None = None
    total_tax: Decimal | None = None
    total_gross: Decimal | None = None
    payment_date: str | None = None  # YYYY-MM-DD
    payment_method: str | None = None
    payment_reference: str | None = None
    payer_iban: str | None = None

    # Validation warnings (e.g. unknown ZUGFeRD profile, line item math errors)
    warnings: list[str] = []

    # Token usage (only for LLM extractions)
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_cents: float | None = None

    # Provider detection (populated by post-processing for EU service providers)
    # Enables automatic Reverse Charge tax rule + bulk link suggestion
    detected_provider: str | None = None  # e.g., "etsy", "paypal", "google"
    suggested_tax_rule: str | None = None  # e.g., "rc_eu_no_vst", "rc_eu_with_vst"
    is_marketplace_invoice: bool = False  # True if bulk-link to fees should be suggested
