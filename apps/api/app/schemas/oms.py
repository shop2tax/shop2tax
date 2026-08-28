"""OMS integration Pydantic schemas (provider-agnostic API surface)."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.oms_provider import OmsProviderType

# --- Provider Schemas ---


class OmsProviderInfoResponse(BaseModel):
    """Response schema for a configured OMS provider."""

    id: str
    type: OmsProviderType
    display_name: str
    is_active: bool


# --- Request Schemas ---


class OmsStoreCreate(BaseModel):
    """Request schema for creating an OMS store mapping."""

    store_type: str  # etsy, amazon, shopify, etc.
    label: str
    external_shop_id: int
    provider_id: str | None = None
    source_config_id: str | None = None
    match_strategy: str = "order_number"  # "order_number" or "email"


class OmsStoreUpdate(BaseModel):
    """Request schema for updating an OMS store mapping."""

    store_type: str | None = None
    label: str | None = None
    external_shop_id: int | None = None
    provider_id: str | None = None
    source_config_id: str | None = None
    match_strategy: str | None = None


class OmsLinkRequest(BaseModel):
    """Request schema for linking a transaction to an OMS order."""

    oms_order_id: str
    # For partial payments: how much of the order is covered by this transaction.
    # If None, full order amount is assumed.
    amount_covered: Decimal | None = None


# --- Response Schemas ---


class OmsOrderItemResponse(BaseModel):
    """Single item within an OMS order."""

    product_title: str
    quantity: int
    total_price: Decimal
    sku: str | None
    tax_index: int = 1
    tax_amount: Decimal = Decimal("0")


class OmsOrderResponse(BaseModel):
    """Response schema for an OMS order."""

    order_id: str
    order_number: str
    invoice_number: str | None
    invoice_number_prefix: str | None
    state: int
    created_at: datetime
    total_cost: Decimal
    currency: str
    customer_name: str
    customer_email: str | None
    shop_id: int
    shop_name: str | None
    platform: str | None
    items: list[OmsOrderItemResponse]
    tags: list[str]
    paid_amount: Decimal
    is_paid: bool
    paid_at: date | None = None
    tax_rate_1: Decimal | None = None
    tax_rate_2: Decimal | None = None


class OmsOrderListResponse(BaseModel):
    """Paginated list of OMS orders."""

    items: list[OmsOrderResponse]
    total: int
    cached: bool
    cache_expires_at: datetime | None


class OmsStoreResponse(BaseModel):
    """Response schema for an OMS store mapping."""

    id: str
    store_type: str
    label: str
    external_shop_id: int
    provider_id: str | None = None
    source_config_id: str | None = None
    source_config_name: str | None = None  # Name of linked TransactionSourceConfig
    match_strategy: str = "order_number"
    created_at: datetime
    updated_at: datetime


class OmsSettingsResponse(BaseModel):
    """Response schema for OMS settings."""

    has_credentials: bool
    stores: list[OmsStoreResponse]


class OmsMatchSuggestion(BaseModel):
    """Suggested OMS order match for a transaction."""

    oms_order_id: str
    order_number: str
    confidence: float  # 0.0 - 1.0
    match_reasons: list[str]
    order_amount: Decimal
    order_date: datetime
    customer_name: str


class OmsBulkMatchRequest(BaseModel):
    """Request schema for bulk matching transactions to OMS orders."""

    # Optional: only match transactions from specific sources
    sources: list[str] | None = None
    # Whether to overwrite existing OMS links
    overwrite_existing: bool = False


class OmsBulkMatchResponse(BaseModel):
    """Response schema for bulk matching results."""

    matched_count: int
    unmatched_count: int
    skipped_count: int
    matched_transaction_ids: list[str]


# --- Sync Log Schemas ---


class OmsSyncLogResponse(BaseModel):
    """Response schema for a single OMS sync log entry."""

    id: str
    start_date: datetime
    end_date: datetime
    fetched_count: int
    imported_count: int
    skipped_count: int
    status: str
    error_message: str | None
    created_at: datetime


class OmsSyncLogListResponse(BaseModel):
    """Paginated list of OMS sync log entries."""

    items: list[OmsSyncLogResponse]
    total: int
