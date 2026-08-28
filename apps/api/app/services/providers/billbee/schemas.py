"""Billbee-internal API representation (D-3).

These types model the Billbee REST API response shape. They are used ONLY inside
the Billbee provider (parsing + _to_oms_order mapping); the rest of the app sees
the generic OmsOrder instead.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class BillbeeOrderItem(BaseModel):
    """Single item within a Billbee order."""

    billbee_id: int
    product_title: str
    quantity: int
    total_price: Decimal
    sku: str | None
    tax_index: int = 1  # 1 = TaxRate1, 2 = TaxRate2
    tax_amount: Decimal = Decimal("0")


class BillbeeAddress(BaseModel):
    """Address information from a Billbee order.

    All fields nullable — Billbee API returns null for missing address parts.
    """

    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    street: str | None = None
    house_number: str | None = None
    zip_code: str | None = None
    city: str | None = None
    country: str | None = None
    email: str | None = None


class BillbeeOrder(BaseModel):
    """Internal representation of a Billbee order."""

    billbee_order_id: int
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
    items: list[BillbeeOrderItem]
    invoice_address: BillbeeAddress | None
    tags: list[str]
    paid_amount: Decimal
    is_paid: bool
    paid_at: date | None = None
    tax_rate_1: Decimal | None = None
    tax_rate_2: Decimal | None = None
