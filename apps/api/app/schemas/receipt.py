"""Receipt Pydantic schemas."""

from __future__ import annotations

import datetime
import re
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, field_validator

from app.models.receipt import ReceiptStatus, ReceiptType
from app.models.receipt_line_item import TaxRule

_UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _validate_uuid_format(value: str) -> str:
    if not _UUID_PATTERN.match(value):
        msg = f"Invalid UUID format: {value}"
        raise ValueError(msg)
    return value


UuidStr = Annotated[str, AfterValidator(_validate_uuid_format)]

# --- Request Schemas ---


class ReceiptLineItemCreate(BaseModel):
    """Request schema for creating a receipt line item."""

    description: str = ""
    amount: Decimal
    skr03_account_id: int | None = None
    tax_rule: TaxRule = TaxRule.TAX_INCLUDED
    tax_rate: Decimal = Decimal("19.00")
    depreciation: str | None = None


class ReceiptCreate(BaseModel):
    """Request schema for creating a receipt.

    Requires `line_items` array (at least one position required).
    """

    receipt_number: str
    date: datetime.date
    counterparty: str
    type: ReceiptType = ReceiptType.EXPENSE
    description: str = ""

    # Line items (required, at least one)
    line_items: list[ReceiptLineItemCreate]

    # Optional fields
    status: ReceiptStatus = ReceiptStatus.FINAL
    due_date: datetime.date | None = None
    payment_date: datetime.date | None = None
    delivery_date: datetime.date | None = None
    delivery_period: str | None = None
    currency: str = "EUR"
    extraction_source: str | None = None  # "zugferd", "gemini", "openai", "anthropic", "manual"

    @field_validator("line_items", mode="after")
    @classmethod
    def validate_line_items_not_empty(cls, line_items: list[ReceiptLineItemCreate]) -> list[ReceiptLineItemCreate]:
        """Ensure at least one line item is provided."""
        if not line_items:
            msg = "At least one line_item is required"
            raise ValueError(msg)
        return line_items


class ReceiptCreateAndLink(ReceiptCreate):
    """Request schema for creating a receipt and linking to a transaction in one call."""

    transaction_id: str


class ReceiptCreateAndLinkBulk(ReceiptCreate):
    """Request schema for creating a receipt and bulk-linking to transactions (Sammelbeleg).

    Used when creating a receipt from selected transactions (e.g., Etsy-PDF → 200 Fees).
    Frontend: `/receipts/new?bulk_transaction_ids=xxx,yyy`
    """

    transaction_ids: list[UuidStr]

    @field_validator("transaction_ids", mode="after")
    @classmethod
    def validate_not_empty(cls, transaction_ids: list[str]) -> list[str]:
        """Ensure at least one transaction ID is provided."""
        if not transaction_ids:
            msg = "At least one transaction_id is required"
            raise ValueError(msg)
        return transaction_ids


class ReceiptUpdate(BaseModel):
    """Request schema for updating a draft receipt.

    All fields are optional — only provided fields will be updated.
    Cannot update final/locked receipts.
    """

    model_config = ConfigDict(extra="forbid")

    receipt_number: str | None = None
    date: datetime.date | None = None
    counterparty: str | None = None
    description: str | None = None
    due_date: datetime.date | None = None
    payment_date: datetime.date | None = None
    delivery_date: datetime.date | None = None
    delivery_period: str | None = None
    currency: str | None = None
    extraction_source: str | None = None
    line_items: list[ReceiptLineItemCreate] | None = None


class RecordPaymentRequest(BaseModel):
    """Request schema for manually recording a payment for a receipt."""

    source_config_id: str
    date: datetime.date
    amount: Decimal | None = None
    counterparty: str | None = None
    description: str | None = None


class ReceiptLinkRequest(BaseModel):
    """Request schema for linking a receipt to a payment."""

    transaction_id: UuidStr


class ReceiptUnlinkRequest(BaseModel):
    """Request schema for unlinking a receipt from a specific transaction.

    If transaction_id is None, all links are removed (backwards-compatible).
    """

    transaction_id: UuidStr | None = None


class ReceiptLockRequest(BaseModel):
    """Request schema for locking receipts in a date range."""

    start_date: datetime.date
    end_date: datetime.date


class BulkLinkRequest(BaseModel):
    """Request schema for bulk-linking transactions to a receipt (Sammelbeleg)."""

    transaction_ids: list[UuidStr]

    @field_validator("transaction_ids", mode="after")
    @classmethod
    def validate_not_empty(cls, transaction_ids: list[str]) -> list[str]:
        """Ensure at least one transaction ID is provided."""
        if not transaction_ids:
            msg = "At least one transaction_id is required"
            raise ValueError(msg)
        return transaction_ids


class BulkUnlinkRequest(BaseModel):
    """Request schema for bulk-unlinking transactions from a receipt.

    Requires explicit transaction IDs — empty list is rejected to prevent accidental mass-unlink.
    """

    transaction_ids: list[UuidStr]

    @field_validator("transaction_ids", mode="after")
    @classmethod
    def validate_not_empty(cls, transaction_ids: list[str]) -> list[str]:
        """Prevent accidental mass-unlink by requiring explicit IDs."""
        if not transaction_ids:
            msg = "At least one transaction_id is required. To unlink all, provide all transaction IDs explicitly."
            raise ValueError(msg)
        return transaction_ids


# --- Response Schemas ---


class ReceiptLineItemResponse(BaseModel):
    """Response schema for a receipt line item."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    description: str
    amount: Decimal
    skr03_account_id: int | None
    skr03_account_number: int | None = None
    skr03_account_name: str | None = None
    tax_rule: TaxRule
    tax_rate: Decimal
    depreciation: str | None

    # Reverse Charge computed fields
    reverse_charge_tax_amount: Decimal | None = None  # 19% RC tax if applicable
    effective_tax_rate: Decimal | None = None  # Always 19% for RC, otherwise tax_rate


class TagResponse(BaseModel):
    """Response schema for a tag."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str


class LinkedTransactionSummary(BaseModel):
    """Summary of a linked transaction."""

    id: str
    date: datetime.date
    amount: Decimal
    counterparty: str
    source_config_name: str | None = None


class ReceiptResponse(BaseModel):
    """Response schema for a single receipt."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    type: ReceiptType
    status: ReceiptStatus
    receipt_number: str
    date: datetime.date
    amount: Decimal  # Computed from line_items (sum)
    counterparty: str
    description: str

    # Optional fields
    due_date: datetime.date | None
    payment_date: datetime.date | None
    delivery_date: datetime.date | None
    delivery_period: str | None
    currency: str
    extraction_source: str | None

    # Line items (SKR03 accounts are per line item)
    line_items: list[ReceiptLineItemResponse] = []

    # Tags
    tags: list[TagResponse] = []

    # OMS provider fields (revenue)
    oms_order_id: str | None
    oms_invoice_number: str | None
    oms_shop_name: str | None
    oms_platform: str | None

    # File attachment
    has_file: bool = False
    file_original_name: str | None = None
    file_mime_type: str | None = None

    # GoBD status
    is_locked: bool
    locked_at: datetime.datetime | None

    # Payment status (synced on link/unlink)
    payment_status: str

    # Open amount: receipt total - abs(linked transaction amount)
    open_amount: Decimal

    # Link status (M:N from junction table)
    # Note: linked_transaction_id and linked_transaction are deprecated (kept for backwards compat)
    # Use linked_transactions for the full list (Sammelbeleg: 1 Receipt → N Transactions)
    linked_transaction_id: str | None = None  # First linked, deprecated
    linked_transaction: LinkedTransactionSummary | None = None  # First linked, deprecated
    linked_transactions: list[LinkedTransactionSummary] = []  # All linked transactions

    # Reverse Charge aggregates
    total_reverse_charge_tax: Decimal = Decimal("0.00")  # Sum of all RC tax (§13b USt)
    has_reverse_charge_items: bool = False  # True if any line item uses RC

    # Timestamps
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ReceiptListResponse(BaseModel):
    """Response schema for paginated receipt list."""

    receipts: list[ReceiptResponse]
    total: int


class ReceiptMatchSuggestion(BaseModel):
    """A suggested match between receipt and payment."""

    id: str  # Transaction ID
    counterparty: str | None
    source_config_name: str | None = None
    amount: Decimal
    date: datetime.date
    confidence: float
    reasons: list[str]


class ReceiptSuggestionForPayment(BaseModel):
    """A suggested receipt for a payment (reverse lookup)."""

    id: str  # Receipt ID
    receipt_number: str
    type: ReceiptType
    counterparty: str
    amount: Decimal
    date: datetime.date
    confidence: float
    reasons: list[str]


class AccountSuggestionResponse(BaseModel):
    """Response schema for SKR03 account suggestion."""

    skr03_account_id: int
    confidence: float
    pattern: str


class SyncResultResponse(BaseModel):
    """Response schema for OMS sync result."""

    imported_count: int
    skipped_count: int
    pdf_count: int = 0
    pdf_error_count: int = 0
    errors: list[str]


class BulkLinkResponse(BaseModel):
    """Response schema for bulk-link operation (Sammelbeleg)."""

    linked_count: int
    skipped_count: int  # Already linked transactions
    receipt_open_amount: Decimal  # Receipt total - sum(abs(linked tx amounts))
    amount_difference: Decimal  # Receipt total - sum(linked tx amounts)
    is_amount_matched: bool  # True if difference <= 0.02€


class BulkUnlinkResponse(BaseModel):
    """Response schema for bulk-unlink operation."""

    unlinked_count: int
    remaining_link_count: int  # Links still active after unlink


class TransactionGroup(BaseModel):
    """A group of transactions by type/category."""

    type: str  # e.g., "Transaction Fees", "Einstellgebühren"
    count: int
    total: Decimal
    transaction_ids: list[str]


class BulkSuggestionResponse(BaseModel):
    """Response schema for bulk-link suggestions (Sammelbeleg matching)."""

    transactions: list["TransactionSummary"]  # Individual transactions
    groups: list[TransactionGroup]  # Grouped by type
    total: Decimal  # Sum of all suggested transactions
    receipt_amount: Decimal  # Receipt total
    difference: Decimal  # receipt_amount - total
    is_amount_matched: bool  # True if abs(difference) <= 0.02€
    source_config_id: str | None  # Source used for matching


class TransactionSummary(BaseModel):
    """Summary of a transaction for suggestions."""

    id: str
    date: datetime.date
    amount: Decimal
    counterparty: str | None
    description: str
    type: str | None  # From extra_data.marketplace_type or parsed from description


class RCComplianceSummary(BaseModel):
    """Summary of Reverse Charge (§13b) items for UStVA compliance.

    Used to show Kleinunternehmer that they need to file UStVA when §13b applies.
    Even Kleinunternehmer must file UStVA for Reverse Charge transactions.
    """

    has_rc_items: bool  # Any RC items in the period?
    rc_net_total: Decimal  # Sum of RC line item amounts (Kz.46 Bemessungsgrundlage)
    rc_tax_total: Decimal  # Sum of RC VAT at 19% (Kz.47 USt)
    rc_input_tax_total: Decimal  # Sum of claimable input tax (Kz.67, only if Regelbesteuert)
    is_small_business: bool  # From SiteSettings — affects Kz.67
    rc_item_count: int  # Number of line items with RC
    period_label: str | None  # Human-readable period (e.g., "Januar 2026")
