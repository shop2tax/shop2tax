"""DATEV export schemas."""

from __future__ import annotations

import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class DatevConfig(BaseModel):
    """DATEV export configuration (from user settings or request)."""

    beraternummer: str = Field(..., description="Consultant number from Steuerberater (7 digits)")
    mandantennummer: str = Field(..., description="Client number at Steuerberater (5 digits)")
    wirtschaftsjahr_beginn: datetime.date = Field(..., description="Start of fiscal year (e.g., 2026-01-01)")
    sachkontenlaenge: int = Field(default=4, description="Account number length (4 for SKR03)")


class DatevExportRequest(BaseModel):
    """Request schema for DATEV export."""

    config: DatevConfig
    date_from: datetime.date | None = Field(None, description="Export from date (inclusive)")
    date_to: datetime.date | None = Field(None, description="Export to date (inclusive)")
    include_unreconciled: bool = Field(
        default=False,
        description="Include unreconciled transactions (default: only reconciled)",
    )


class DatevZipExportRequest(BaseModel):
    """Request schema for DATEV ZIP export with Belegbilder."""

    config: DatevConfig
    date_from: datetime.date | None = Field(None, description="Export from date (inclusive)")
    date_to: datetime.date | None = Field(None, description="Export to date (inclusive)")
    include_receipts: bool = Field(
        default=True,
        description="Include Belegbilder in nested ZIPs (default: True)",
    )
    finalized_only: bool = Field(
        default=False,
        description="Only include finalized receipts (default: False)",
    )
    document_types: list[str] | None = Field(
        default=None,
        description="Filter by document types: ['revenue', 'expense'] (default: all)",
    )


class DatevBookingLine(BaseModel):
    """Single DATEV booking line.

    Follows DATEV Buchungsstapel format with 124 columns. Key columns:
    - Column 1: Umsatz (gross amount)
    - Column 2: Soll/Haben (S=debit, H=credit)
    - Column 7: Konto (SKR03 account)
    - Column 8: Gegenkonto (contra account)
    - Column 9: BU-Schlüssel (tax key)
    - Column 14: Buchungstext (booking text)
    - Column 20: Beleglink (BEDI GUID for document linking)
    - Columns 21-36: Beleginfo fields (description, VAT, name, amounts, etc.)
    """

    umsatz: Decimal = Field(..., description="Gross amount (always positive)")
    soll_haben: str = Field(..., description="S=debit, H=credit")
    waehrung: str = Field(default="EUR", description="Currency code")
    konto: int = Field(..., description="SKR03 account number")
    gegenkonto: int = Field(..., description="Contra account number")
    bu_schluessel: int | None = Field(None, description="Tax key (2=7%USt, 3=19%USt, 8=7%VSt, 9=19%VSt)")
    belegfeld_1: str = Field(..., description="Document reference (transaction ID)")
    belegfeld_2: str | None = Field(None, description="Additional reference")
    datum: datetime.date = Field(..., description="Booking date")
    buchungstext: str = Field(..., description="Booking text (counterparty/description)")
    ust_satz: Decimal | None = Field(None, description="VAT rate in percent")
    netto: Decimal | None = Field(None, description="Net amount")
    ust_betrag: Decimal | None = Field(None, description="VAT amount")

    # New fields for ZIP export (column 20 + columns 21-36)
    beleglink: str | None = Field(None, description='BEDI GUID link (format: BEDI "uuid")')
    receipt_id: str | None = Field(None, description="Receipt ID for file lookup")
    beleginfo_beschreibung: str | None = Field(None, description="Beleginfo: Description")
    beleginfo_ust_prozent: str | None = Field(None, description="Beleginfo: VAT percent")
    beleginfo_name: str | None = Field(None, description="Beleginfo: Counterparty name")
    beleginfo_nettobetrag: Decimal | None = Field(None, description="Beleginfo: Net amount")
    beleginfo_steuerbetrag: Decimal | None = Field(None, description="Beleginfo: VAT amount")
    beleginfo_leistungsdatum: str | None = Field(None, description="Beleginfo: Service date (DDMMYYYY)")


class DatevExportResponse(BaseModel):
    """Response for DATEV export."""

    header: list[str] = Field(..., description="DATEV header block (2 lines)")
    column_headers: list[str] = Field(..., description="Column header row")
    rows: list[list[str]] = Field(..., description="Data rows")
    transaction_count: int = Field(..., description="Number of transactions exported")
    line_item_count: int = Field(..., description="Number of line items (for split bookings)")
    csv_content: str = Field(..., description="Complete CSV content for download")


class DatevValidationResult(BaseModel):
    """Result of DATEV format validation."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExportLogResponse(BaseModel):
    """Response schema for export log entry."""

    id: str
    export_type: str
    export_format: str  # csv or zip
    transaction_count: int
    line_item_count: int
    date_from: datetime.date | None
    date_to: datetime.date | None
    beraternummer: str
    mandantennummer: str
    filename: str | None
    created_at: str  # ISO 8601 format


class ExportHistoryResponse(BaseModel):
    """Response for export history list."""

    items: list[ExportLogResponse]
    total: int


class DatevZipExportResponse(BaseModel):
    """Response for DATEV ZIP export with Belegbilder."""

    zip_content: bytes = Field(..., description="ZIP file content")
    filename: str = Field(..., description="Suggested filename")
    transaction_count: int = Field(..., description="Number of transactions exported")
    line_item_count: int = Field(..., description="Number of line items")
    revenue_receipt_count: int = Field(..., description="Number of revenue receipts with files")
    expense_receipt_count: int = Field(..., description="Number of expense receipts with files")
    receipts_without_file: list[str] = Field(default_factory=list, description="Receipt numbers without files")
    zip_size_bytes: int = Field(..., description="ZIP file size in bytes")
