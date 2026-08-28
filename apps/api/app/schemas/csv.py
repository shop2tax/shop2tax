"""CSV parsing Pydantic schemas."""

from __future__ import annotations

import datetime
from decimal import Decimal

from pydantic import BaseModel


class CsvFormatInfo(BaseModel):
    """Information about a detected CSV format."""

    source: str  # Source name (e.g., "Etsy", "Amazon", "Stripe")
    source_config_id: str | None = None  # FK to TransactionSourceConfig (for import)
    config_name: str
    delimiter: str
    row_count: int


class ParsedRowResponse(BaseModel):
    """Response for a single parsed CSV row (preview)."""

    date: datetime.date | None = None
    amount: Decimal | None = None
    counterparty: str | None = None
    description: str | None = None
    source_reference: str | None = None


class CsvDetectResponse(BaseModel):
    """Response from CSV format detection endpoint."""

    success: bool
    format: CsvFormatInfo | None = None
    error: str | None = None


class CsvParseResponse(BaseModel):
    """Response from CSV parse endpoint."""

    success: bool
    source: str | None = None  # Source name (e.g., "Etsy", "Amazon")
    source_config_id: str | None = None  # FK to TransactionSourceConfig (for import)
    config_name: str | None = None
    row_count: int = 0
    rows: list[ParsedRowResponse] = []
    error: str | None = None


class CsvUploadResponse(BaseModel):
    """Response from CSV upload endpoint (detection + preview)."""

    success: bool
    filename: str
    format: CsvFormatInfo | None = None
    preview_rows: list[ParsedRowResponse] = []
    total_rows: int = 0
    error: str | None = None


# --- Generic CSV Import Schemas (for bank imports with column mapping) ---


class SuggestedColumns(BaseModel):
    """Auto-detected column assignments based on header names and sample values."""

    column_date: str | None = None
    column_amount: str | None = None
    column_counterparty: str | None = None
    column_description: str | None = None
    column_reference: str | None = None


class CsvAnalyzeResponse(BaseModel):
    """Response from CSV analyze endpoint.

    Returns detected options and column information for mapping UI.
    """

    success: bool
    filename: str

    # Detected parsing options (editable in UI)
    delimiter: str | None = None
    encoding: str | None = None
    has_header: bool = True
    skip_rows: int = 0
    date_format: str | None = None
    date_ambiguous: bool = False  # True if DD/MM vs MM/DD ambiguity
    amount_format: str | None = None  # "german" or "english"

    # Column information for mapping UI
    column_headers: list[str] = []
    sample_values: dict[str, list[str]] = {}  # column_name -> first 5 values
    unique_values: dict[str, list[str]] = {}  # column_name -> ALL unique values (for filter dropdowns)

    # Auto-detected column suggestions (pre-fill dropdowns in UI)
    suggested_columns: SuggestedColumns | None = None

    error: str | None = None


class GenericCsvMappingRequest(BaseModel):
    """Request schema for parsing CSV with user-provided mapping.

    Used with /csv/parse-generic and /csv/enrich endpoints.
    Bank imports require date+amount+counterparty+description.
    Marketplace imports only need reference (+ optional date/amount for comparison).
    """

    # CSV parsing options
    delimiter: str = ","
    encoding: str = "utf-8"
    has_header: bool = True
    skip_rows: int = 0
    date_format: str | None = None
    amount_format: str = "english"  # "german" or "english"

    # Column assignments (all optional — marketplace only needs reference)
    column_date: str | None = None
    column_amount: str | None = None
    column_counterparty: str | None = None
    column_description: str | None = None
    column_reference: str | None = None

    # Filter (optional, for marketplace imports)
    column_filter: str | None = None
    # NOTE: filter_include_values is NOT here — it's a separate Query() param in the router
    # because Depends() with Pydantic can't parse list[str] from repeated query params


class GenericCsvParseResponse(BaseModel):
    """Response from generic CSV parse endpoint.

    Returns parsed rows for preview before import.
    """

    success: bool
    row_count: int = 0
    rows: list[ParsedRowResponse] = []
    errors: list[str] = []  # Per-row error messages
    filtered_count: int = 0  # Rows removed by filter
    error: str | None = None  # Overall error


# --- Enrichment Schemas ---


class EnrichedRowResponse(BaseModel):
    """A CSV row enriched with OMS order data."""

    date: datetime.date | None = None
    amount: Decimal | None = None
    counterparty: str | None = None
    description: str | None = None
    source_reference: str | None = None
    enriched_counterparty: str | None = None  # Customer name from OMS
    enriched_description: str | None = None  # Invoice number from OMS
    enriched_date: datetime.date | None = None  # Order date from OMS
    enriched_amount: Decimal | None = None  # Total cost from OMS
    match_status: str  # "matched" | "unmatched" | "no_enrichment"


class CsvEnrichResponse(BaseModel):
    """Response from CSV enrich endpoint."""

    success: bool
    rows: list[EnrichedRowResponse] = []
    total_rows: int = 0
    matched_count: int = 0
    unmatched_count: int = 0
    errors: list[str] = []
    error: str | None = None
    timing: dict[str, float] | None = None


# --- File-based CSV Upload (server-side file reference) ---


class CsvFileUploadResponse(BaseModel):
    """Response from CSV file upload endpoint.

    Returns a file_id that can be used in follow-up requests
    (analyze, parse-generic, enrich) instead of re-uploading.
    """

    success: bool
    file_id: str | None = None
    filename: str
    expires_at: datetime.datetime | None = None
    error: str | None = None


# --- Marketplace CSV Schemas (for dedicated parsers: Etsy, Amazon, Shopify) ---


class MarketplaceParsedRowResponse(BaseModel):
    """Response for a single marketplace-parsed CSV row (preview).

    Extends ParsedRowResponse with marketplace-specific fields for richer preview.
    Works with all marketplace parsers (Etsy, Shopify, Amazon).
    """

    date: datetime.date
    amount: Decimal
    counterparty: str
    description: str
    source_reference: str | None = None
    marketplace_type: str | None = None  # Transaction type (e.g., "sale", "refund", "charge", "payout")
    suggested_skr03: int | None = None
    order_id: str | None = None
    oms_order_id: str | None = None  # Set by OMS enrichment, primary key for auto-receipt-linking
    is_internal_transfer: bool = False
    is_rc_eligible: bool = False  # §13b Reverse Charge eligible (set by parser)
    rc_fee_amount: Decimal | None = None  # Fee amount for RC calculation (Etsy: abs(amount) for fee rows, Shopify: Fee column)
    import_hash: str | None = None
    extra_data: dict | None = None


class MarketplaceCsvParseResponse(BaseModel):
    """Response from marketplace CSV parse endpoint.

    Returns enriched rows with type detection and SKR03 assignment.
    """

    success: bool
    row_count: int = 0
    rows: list[MarketplaceParsedRowResponse] = []
    errors: list[str] = []
    skipped_rows: int = 0
    error: str | None = None
    enrichment: dict | None = None  # OMS enrichment stats: {matched, unmatched, skipped, error?}
    rc_ust_amount: Decimal | None = None  # §13b RC USt on eligible fees (19% of fee total)
