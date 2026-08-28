"""OMS provider abstraction: generic order types, Protocol, and factory.

An OmsProvider is a pluggable Order Management System integration. Billbee is the
first implementation (see services/providers/billbee/). Concrete providers map their
own API types to the generic OmsOrder/OmsOrderItem dataclasses defined here, so that
sync, enrichment, and matching stay provider-agnostic.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.oms_provider import OmsProviderRecord, OmsProviderType


@dataclass(frozen=True)
class OmsProviderInfo:
    """Provider metadata from the DB (oms_providers row)."""

    id: str
    type: OmsProviderType
    display_name: str
    is_active: bool


@dataclass(frozen=True)
class OmsOrderItem:
    """Line item from an OMS order."""

    product_title: str
    quantity: int
    total_price: Decimal
    sku: str | None
    tax_index: int  # 1 = primary rate, 2 = secondary rate
    tax_amount: Decimal


@dataclass(frozen=True)
class OmsOrder:
    """Full order from an OMS — all fields used by sync + enrichment + matching."""

    order_id: str
    order_number: str
    invoice_number: str | None
    invoice_number_prefix: str | None
    state: int  # Provider-specific state code
    created_at: datetime
    total_cost: Decimal
    currency: str
    customer_name: str
    customer_email: str | None
    shop_id: int
    shop_name: str | None
    platform: str | None
    items: list[OmsOrderItem]
    tags: list[str]
    paid_amount: Decimal
    is_paid: bool
    paid_at: date | None
    tax_rate_1: Decimal | None
    tax_rate_2: Decimal | None


@dataclass(frozen=True)
class EnrichmentResult:
    """Typed enrichment data extracted from a matched OMS order."""

    oms_order_id: str
    invoice_number: str | None
    shop_name: str | None
    platform: str | None
    customer_name: str | None
    order_date: date | None


@runtime_checkable
class OmsProvider(Protocol):
    """Pluggable OMS integration provider."""

    @property
    def provider_type(self) -> OmsProviderType: ...

    @property
    def display_name(self) -> str: ...

    async def fetch_orders(
        self, store_ids: list[int] | None = None, min_date: datetime | None = None, max_date: datetime | None = None
    ) -> list[OmsOrder]: ...

    async def fetch_orders_cached(
        self,
        store_ids: list[int] | None = None,
        min_date: datetime | None = None,
        max_date: datetime | None = None,
        force_refresh: bool = False,
    ) -> tuple[list[OmsOrder], bool, datetime | None]:
        """Returns (orders, is_cached, cache_expires_at). Caching is provider-internal (D-4)."""
        ...

    async def fetch_order_by_id(self, order_id: str) -> OmsOrder | None: ...

    async def fetch_invoice_pdf(self, order_id: str) -> tuple[bytes | None, str | None]:
        """Returns (pdf_bytes, error_message) — never (None, None)."""
        ...

    async def set_labels(self, order_ids: list[str], label: str) -> tuple[int, list[str]]:
        """Returns (success_count, errors)."""
        ...

    def enrich_transaction(self, order: OmsOrder) -> EnrichmentResult: ...


def get_oms_providers(db: Session) -> list[OmsProviderInfo]:
    """Get all active providers from the DB."""
    records = db.scalars(select(OmsProviderRecord).where(OmsProviderRecord.is_active).order_by(OmsProviderRecord.display_name)).all()
    return [OmsProviderInfo(id=record.id, type=record.type, display_name=record.display_name, is_active=record.is_active) for record in records]


def get_oms_provider(provider_id: str, db: Session) -> OmsProvider | None:
    """Factory: instantiate a concrete provider by its DB record ID.

    Returns None if the record is missing, inactive, or its credentials are not
    configured in the environment.
    """
    from app.config import get_settings
    from app.services.providers.billbee import BillbeeProvider

    record = db.get(OmsProviderRecord, provider_id)
    if record is None or not record.is_active:
        return None

    if record.type == OmsProviderType.BILLBEE:
        settings = get_settings()
        if not settings.billbee_api_key:
            return None
        return BillbeeProvider(
            api_key=settings.billbee_api_key,
            username=settings.billbee_username,
            password=settings.billbee_password,
            display_name=record.display_name,
        )

    return None


def get_default_oms_provider(db: Session) -> OmsProvider | None:
    """Convenience: instantiate the first active provider (single-provider deployments)."""
    record = db.scalars(select(OmsProviderRecord).where(OmsProviderRecord.is_active).order_by(OmsProviderRecord.display_name)).first()
    if record is None:
        return None
    return get_oms_provider(record.id, db)
