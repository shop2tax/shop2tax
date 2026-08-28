"""Transaction source and CSV mapping profile Pydantic schemas."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.source import SourceType

# --- Shared Validators (DRY) ---


def _validate_source_name(value: str | None) -> str | None:
    """Validate source name: not empty, max 100 chars. Handles None for updates."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        msg = "Source name cannot be empty"
        raise ValueError(msg)
    if len(value) > 100:
        msg = "Source name cannot exceed 100 characters"
        raise ValueError(msg)
    return value


def _validate_check_account(value: int | None) -> int | None:
    """Validate SKR03 check account range: 1200-1288 or 1590."""
    from app.core.constants import is_valid_check_account

    if value is not None and not is_valid_check_account(value):
        msg = "Check account must be between 1200 and 1288, or 1590 (Durchlaufende Posten)"
        raise ValueError(msg)
    return value


# --- TransactionSourceConfig Schemas ---


class TransactionSourceConfigCreate(BaseModel):
    """Request schema for creating a source."""

    name: str
    type: SourceType = SourceType.CSV_MAPPING
    check_account_id: int | None = None  # Auto-assigned if None
    source_config: MarketplaceSourceConfig | None = None  # Marketplace-specific config (parser, has_ust_id_registered)

    _validate_name = field_validator("name")(_validate_source_name)
    _validate_account = field_validator("check_account_id")(_validate_check_account)


class MarketplaceSourceConfigUpdate(BaseModel):
    """Request schema for updating marketplace-specific config."""

    parser: str | None = None  # "etsy", "amazon", "shopify"
    has_ust_id_registered: bool | None = None


class TransactionSourceConfigUpdate(BaseModel):
    """Request schema for updating a source."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    type: SourceType | None = None
    check_account_id: int | None = None
    source_config: MarketplaceSourceConfigUpdate | None = None  # For marketplace sources

    _validate_name = field_validator("name")(_validate_source_name)
    _validate_account = field_validator("check_account_id")(_validate_check_account)


class MarketplaceSourceConfig(BaseModel):
    """Marketplace-specific source configuration (stored in source_config JSONB)."""

    parser: str | None = None  # "etsy", "amazon", "shopify" — determines dedicated parser
    has_ust_id_registered: bool = True  # USt-ID bei Marktplatz hinterlegt (affects RC tax treatment)


class TransactionSourceConfigResponse(BaseModel):
    """Response schema for a transaction source."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: SourceType
    check_account_id: int  # SKR03 Buchungskonto (1200-1288)
    is_system: bool  # True if user_id is NULL (marketplace)
    has_mapping: bool  # True if user has a mapping profile for this source
    import_method: str  # Human-readable: "CSV-Parser", "API-Sync", "CSV-Zuordnung", etc.
    source_config: MarketplaceSourceConfig | None = None  # Marketplace-specific config (parser, has_ust_id_registered)
    created_at: datetime.datetime
    updated_at: datetime.datetime


# --- CsvMappingProfile Schemas ---


class CsvMappingProfileCreate(BaseModel):
    """Request schema for creating/updating a CSV mapping profile.

    Used for both create and update (upsert by source_id).
    """

    source_id: str
    name: str | None = None

    # CSV parsing options
    delimiter: str = ","
    encoding: str = "utf-8"
    has_header: bool = True
    skip_rows: int = 0
    date_format: str | None = None
    amount_format: str | None = None  # "german" or "english"

    # Column assignments (all optional — marketplace only needs reference)
    column_date: str | None = None
    column_amount: str | None = None
    column_counterparty: str | None = None
    column_description: str | None = None
    column_reference: str | None = None

    # Filter (for marketplace imports)
    column_filter: str | None = None
    filter_include_values: list[str] | None = None

    @field_validator("delimiter")
    @classmethod
    def validate_delimiter(cls, value: str) -> str:
        if len(value) > 5:
            msg = "Delimiter cannot exceed 5 characters"
            raise ValueError(msg)
        return value

    @field_validator("amount_format")
    @classmethod
    def validate_amount_format(cls, value: str | None) -> str | None:
        if value is not None and value not in ("german", "english"):
            msg = "Amount format must be 'german' or 'english'"
            raise ValueError(msg)
        return value


class CsvMappingProfileUpdate(BaseModel):
    """Request schema for updating a CSV mapping profile."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    delimiter: str | None = None
    encoding: str | None = None
    has_header: bool | None = None
    skip_rows: int | None = None
    date_format: str | None = None
    amount_format: str | None = None

    column_date: str | None = None
    column_amount: str | None = None
    column_counterparty: str | None = None
    column_description: str | None = None
    column_reference: str | None = None

    # Filter (for marketplace imports)
    column_filter: str | None = None
    filter_include_values: list[str] | None = None


class CsvMappingProfileResponse(BaseModel):
    """Response schema for a CSV mapping profile."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    source_name: str
    name: str | None

    # CSV parsing options
    delimiter: str
    encoding: str
    has_header: bool
    skip_rows: int
    date_format: str | None
    amount_format: str | None

    # Column assignments (all nullable — marketplace only needs reference)
    column_date: str | None
    column_amount: str | None
    column_counterparty: str | None
    column_description: str | None
    column_reference: str | None

    # Filter (for marketplace imports)
    column_filter: str | None = None
    filter_include_values: list[str] | None = None

    created_at: datetime.datetime
    updated_at: datetime.datetime
