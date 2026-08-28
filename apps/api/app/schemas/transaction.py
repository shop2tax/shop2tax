"""Transaction Pydantic schemas."""

from __future__ import annotations

import datetime
import re
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

_UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _validate_uuid_format(value: str) -> str:
    if not _UUID_PATTERN.match(value):
        msg = f"Invalid UUID format: {value}"
        raise ValueError(msg)
    return value


UuidStr = Annotated[str, AfterValidator(_validate_uuid_format)]


class TransactionStatus(str, Enum):
    """Computed transaction status based on receipts and flags.

    Status logic:
    - PRIVATE: is_private = true (takes precedence)
    - INTERNAL: is_internal_transfer = true (Geldbewegung)
    - OPEN: No linked receipts
    - ASSIGNED: Has linked receipts but open_amount > 0 (Sammelbuchung not complete)
    - BOOKED: open_amount = 0 (fully covered by receipts)
    - AUTOMATIC: Linked via OMS auto-match
    """

    OPEN = "open"
    ASSIGNED = "assigned"
    BOOKED = "booked"
    AUTOMATIC = "automatic"
    PRIVATE = "private"
    INTERNAL = "internal"


# --- Request Schemas ---


class TransactionCreate(BaseModel):
    """Request schema for creating a transaction."""

    date: datetime.date
    amount: Decimal
    counterparty: str
    description: str
    source_config_id: str  # FK to TransactionSourceConfig
    source_reference: str | None = None
    notes: str | None = None
    is_private: bool = False


class TransactionUpdate(BaseModel):
    """Request schema for updating a transaction.

    All fields are optional - only provided fields will be updated.
    """

    model_config = ConfigDict(extra="forbid")

    date: datetime.date | None = None
    amount: Decimal | None = None
    counterparty: str | None = None
    description: str | None = None
    notes: str | None = None
    is_private: bool | None = None


class MarkPrivateRequest(BaseModel):
    """Request schema for marking a transaction as private."""

    model_config = ConfigDict(extra="forbid")

    is_private: bool


class TransactionImportItem(BaseModel):
    """Single item from CSV import.

    Base fields are required for all imports.
    Marketplace fields (import_hash, is_internal_transfer, extra_data)
    are optional — provided by marketplace parsers, ignored by bank imports.
    """

    date: datetime.date
    amount: Decimal
    counterparty: str
    description: str
    source_reference: str | None = None
    # Marketplace-specific fields (from parse-marketplace response)
    import_hash: str | None = None
    is_internal_transfer: bool = False
    extra_data: dict | None = None
    oms_order_id: str | None = None  # Set by OMS enrichment, enables auto-receipt-linking


class TransactionImportRequest(BaseModel):
    """Request schema for bulk import from parsed CSV.

    Requires source_config_id (FK to TransactionSourceConfig).
    """

    source_config_id: str  # Required - FK to TransactionSourceConfig
    items: list[TransactionImportItem]
    skip_duplicates: bool = True


# --- Response Schemas ---


class LinkedReceiptSummary(BaseModel):
    """Summary of a linked receipt (for transaction response)."""

    id: str
    receipt_number: str
    counterparty: str
    amount: Decimal
    date: datetime.date
    type: str  # 'revenue' or 'expense'
    has_file: bool


class TransferSuggestion(BaseModel):
    """A suggested counter-transaction for internal transfer (Geldbewegung)."""

    id: str
    date: datetime.date
    amount: Decimal
    counterparty: str
    source_config_name: str | None  # Display name of the source
    description: str


class TransferLinkRequest(BaseModel):
    """Request schema for linking two transactions as internal transfer."""

    target_transaction_id: str


class TransactionResponse(BaseModel):
    """Response schema for a single transaction."""

    id: str
    date: datetime.date
    amount: Decimal
    counterparty: str
    description: str
    source_reference: str | None
    oms_order_id: str | None
    notes: str | None
    is_private: bool
    remaining_amount: Decimal | None  # OMS partial payment tracking
    original_currency: str | None
    original_amount: Decimal | None
    exchange_rate: Decimal | None

    # Source config (all imports use this now)
    source_config_id: str | None
    source_config_name: str | None

    # Computed status
    status: TransactionStatus

    # Open amount: abs(amount) - sum(linked_receipt_line_items.amount)
    open_amount: Decimal

    # All linked receipts (from junction table)
    linked_receipts: list[LinkedReceiptSummary]

    # Internal transfer (Geldbewegung)
    is_internal_transfer: bool = False
    linked_transfer_id: str | None = None

    created_at: datetime.datetime
    updated_at: datetime.datetime


class TransactionListResponse(BaseModel):
    """Paginated list of transactions."""

    items: list[TransactionResponse]
    total: int


class TransactionImportError(BaseModel):
    """Error detail for a failed import row."""

    row_index: int
    error: str


class TransactionImportResponse(BaseModel):
    """Response for bulk import operation."""

    imported_count: int
    skipped_count: int
    error_count: int = 0
    errors: list[TransactionImportError] = []
    import_log_id: str
    # Auto-receipt-linking counts (non-zero when imported transactions matched receipts)
    linked_count: int = 0
    no_receipt_count: int = 0
    skipped_locked_count: int = 0


class AutoLinkRequest(BaseModel):
    """Request to auto-link transactions to receipts by oms_order_id."""

    transaction_ids: list[str] | None = None


class AutoLinkResponse(BaseModel):
    """Result of an auto-link operation."""

    linked: int
    already_linked: int
    no_receipt: int
    skipped_locked: int


class FindMatchingReceiptsRequest(BaseModel):
    """Request schema for finding receipts matching selected transactions."""

    transaction_ids: list[UuidStr]


class MatchingReceiptSummary(BaseModel):
    """Summary of a receipt matching the selected transactions."""

    id: str
    receipt_number: str
    date: datetime.date
    counterparty: str
    amount: Decimal
    type: str  # expense/revenue
    has_file: bool
    match_score: float  # 0.0-1.0 based on amount/date match


class FindMatchingReceiptsResponse(BaseModel):
    """Response for find-matching-receipts operation."""

    matching_receipts: list[MatchingReceiptSummary]
    selected_total: Decimal  # Sum of abs(selected transaction amounts)
    transaction_count: int


# --- Payout↔Bank Matching Schemas ---


class PayoutSuggestion(BaseModel):
    """A suggested payout transaction to match a bank deposit."""

    payout_id: str
    payout_date: datetime.date
    payout_amount: Decimal  # Negative (outflow from marketplace clearing account)
    payout_counterparty: str
    payout_source_name: str  # Marketplace name (Etsy, Amazon, etc.)
    payout_check_account: int  # Marketplace clearing account (1201, 1202, etc.)
    match_score: float  # 0.0-1.0, amount match required, date proximity boosts


class BankDepositWithSuggestions(BaseModel):
    """A bank deposit with suggested matching payout transactions."""

    bank_transaction_id: str
    bank_date: datetime.date
    bank_amount: Decimal  # Positive (inflow to bank account)
    bank_counterparty: str
    bank_description: str
    bank_source_name: str
    suggestions: list[PayoutSuggestion]


class PayoutSuggestionsResponse(BaseModel):
    """Response for payout matching suggestions."""

    deposits: list[BankDepositWithSuggestions]
    deposit_count: int


class ConfirmPayoutMatchRequest(BaseModel):
    """Request schema for confirming a payout↔bank match."""

    bank_transaction_id: UuidStr
    payout_transaction_id: UuidStr


class ConfirmPayoutMatchResponse(BaseModel):
    """Response for confirmed payout match.

    Creates linked_transfer between the transactions (Geldtransit-Buchung).
    """

    bank_transaction_id: str
    payout_transaction_id: str
    message: str
