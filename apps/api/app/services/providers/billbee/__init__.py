"""Billbee OmsProvider implementation.

Wraps the Billbee REST API and maps Billbee's API types to the generic OmsOrder
format (D-3). All Billbee-specific logic (HTTP, caching, parsing) lives here; the
rest of the app only sees OmsProvider / OmsOrder.
"""

import asyncio
import base64
import binascii
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx

from app.models.oms_provider import OmsProviderType
from app.services.oms_provider import EnrichmentResult, OmsOrder, OmsOrderItem
from app.services.providers.billbee.schemas import BillbeeAddress, BillbeeOrder, BillbeeOrderItem

logger = logging.getLogger(__name__)

BILLBEE_API_BASE = "https://app.billbee.io/api/v1"
CACHE_DURATION = timedelta(hours=2)


@dataclass
class _CacheEntry:
    """Cached mapped orders for a query."""

    data: list[OmsOrder]
    expires_at: datetime


# Simple in-memory cache (tenant-wide, shared across all users)
_order_cache: dict[str, _CacheEntry] = {}


def _get_cache_key(
    store_ids: list[int] | None,
    min_order_date: datetime | None,
    max_order_date: datetime | None,
) -> str:
    """Generate cache key for an orders query."""
    store_part = ",".join(str(store) for store in sorted(store_ids)) if store_ids else "all"
    date_part = ""
    if min_order_date or max_order_date:
        min_str = min_order_date.isoformat() if min_order_date else ""
        max_str = max_order_date.isoformat() if max_order_date else ""
        date_part = f"|{min_str}..{max_str}"
    return f"{store_part}{date_part}"


def _parse_billbee_order(data: dict) -> BillbeeOrder:
    """Parse a raw Billbee API order into the internal BillbeeOrder schema."""
    items = [
        BillbeeOrderItem(
            billbee_id=item.get("BillbeeId", 0),
            product_title=(item.get("Product") or {}).get("Title", "Unknown"),
            quantity=item.get("Quantity", 1),
            total_price=Decimal(str(item.get("TotalPrice", 0))),
            sku=(item.get("Product") or {}).get("SKU"),
            tax_index=item.get("TaxIndex", 1),
            tax_amount=Decimal(str(item.get("TaxAmount", 0))),
        )
        for item in (data.get("OrderItems") or [])
    ]

    invoice_addr = data.get("InvoiceAddress")
    invoice_address = None
    if invoice_addr:
        # Billbee API returns null for missing fields — coerce None to ""
        invoice_address = BillbeeAddress(
            first_name=invoice_addr.get("FirstName") or "",
            last_name=invoice_addr.get("LastName") or "",
            company=invoice_addr.get("Company"),
            street=invoice_addr.get("Street") or "",
            house_number=invoice_addr.get("HouseNumber"),
            zip_code=invoice_addr.get("Zip") or "",
            city=invoice_addr.get("City") or "",
            country=invoice_addr.get("Country") or "",
            email=invoice_addr.get("Email"),
        )

    seller = data.get("Seller") or {}
    buyer = data.get("Buyer") or {}
    total_cost = Decimal(str(data.get("TotalCost", 0)))
    paid_amount = Decimal(str(data.get("PaidAmount", 0)))

    invoice_number_raw = data.get("InvoiceNumber")
    invoice_number = str(invoice_number_raw) if invoice_number_raw else None
    invoice_number_prefix = data.get("InvoiceNumberPrefix") or None

    created_at_raw = data.get("CreatedAt") or ""
    try:
        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        created_at = datetime(2000, 1, 1, tzinfo=UTC)

    paid_at_raw = data.get("PayedAt") or ""
    try:
        paid_at = datetime.fromisoformat(paid_at_raw.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        paid_at = None

    tax_rate_1_raw = data.get("TaxRate1")
    tax_rate_1 = Decimal(str(tax_rate_1_raw)) if tax_rate_1_raw is not None else None
    tax_rate_2_raw = data.get("TaxRate2")
    tax_rate_2 = Decimal(str(tax_rate_2_raw)) if tax_rate_2_raw is not None else None

    return BillbeeOrder(
        billbee_order_id=data.get("BillBeeOrderId") or 0,
        order_number=data.get("OrderNumber") or "",
        invoice_number=invoice_number,
        invoice_number_prefix=invoice_number_prefix,
        state=data.get("State") or 0,
        created_at=created_at,
        total_cost=total_cost,
        currency=data.get("Currency") or "EUR",
        customer_name=(
            f"{buyer.get('FirstName') or ''} {buyer.get('LastName') or ''}".strip()
            or buyer.get("FullName")
            or (f"{(invoice_addr or {}).get('FirstName') or ''} {(invoice_addr or {}).get('LastName') or ''}".strip() if invoice_addr else "")
            or "Unknown"
        ),
        customer_email=buyer.get("Email") or (invoice_addr or {}).get("Email"),
        shop_id=seller.get("BillbeeShopId") or 0,
        shop_name=seller.get("BillbeeShopName"),
        platform=seller.get("Platform"),
        items=items,
        invoice_address=invoice_address,
        tags=data.get("Tags") or [],
        paid_amount=paid_amount,
        is_paid=paid_amount >= total_cost,
        paid_at=paid_at,
        tax_rate_1=tax_rate_1,
        tax_rate_2=tax_rate_2,
    )


async def _make_billbee_request(
    client: httpx.AsyncClient,
    url: str,
    params: list[tuple[str, str | int | float | None]],
    headers: dict[str, str],
    auth: tuple[str, str],
    method: str = "GET",
    json_body: dict | None = None,
) -> dict:
    """Make a Billbee API request with retry and exponential backoff.

    Retries on 429 (rate limit) and 5xx. On 429 uses Retry-After if present,
    otherwise exponential backoff: 1s, 2s, 4s.
    """
    last_error: Exception | None = None
    retry_delays = [1.0, 2.0, 4.0]

    for attempt in range(3):
        try:
            if method == "GET":
                response = await client.get(url, params=params, headers=headers, auth=auth, timeout=30.0)
            elif method == "POST":
                response = await client.post(url, params=params, headers=headers, auth=auth, json=json_body, timeout=30.0)
            elif method == "PUT":
                response = await client.put(url, params=params, headers=headers, auth=auth, json=json_body, timeout=30.0)
            else:
                msg = f"Unsupported HTTP method: {method}"
                raise ValueError(msg)

            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            if status_code == 429 or status_code >= 500:
                last_error = error
                if attempt < 2:
                    retry_after = error.response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            delay = float(retry_after)
                        except ValueError:
                            delay = retry_delays[attempt]
                    else:
                        delay = retry_delays[attempt]
                    logger.warning(f"Billbee API {status_code} on attempt {attempt + 1}, retrying in {delay}s")
                    await asyncio.sleep(delay)
                    continue
            raise
        except httpx.TimeoutException as error:
            last_error = error
            if attempt < 2:
                delay = retry_delays[attempt]
                logger.warning(f"Billbee API timeout on attempt {attempt + 1}, retrying in {delay}s")
                await asyncio.sleep(delay)
                continue
            raise

    if last_error:
        raise last_error
    msg = "Billbee API request failed after retries"
    raise RuntimeError(msg)


class BillbeeProvider:
    """Billbee implementation of the OmsProvider Protocol."""

    def __init__(self, api_key: str, username: str, password: str, display_name: str = "Billbee") -> None:
        self._api_key = api_key
        self._username = username
        self._password = password
        self._display_name = display_name

    @property
    def provider_type(self) -> OmsProviderType:
        return OmsProviderType.BILLBEE

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Billbee-Api-Key": self._api_key}

    @property
    def _auth(self) -> tuple[str, str]:
        return (self._username, self._password)

    def _to_oms_order_item(self, item: BillbeeOrderItem) -> OmsOrderItem:
        return OmsOrderItem(
            product_title=item.product_title,
            quantity=item.quantity,
            total_price=item.total_price,
            sku=item.sku,
            tax_index=item.tax_index,
            tax_amount=item.tax_amount,
        )

    def _to_oms_order(self, order: BillbeeOrder) -> OmsOrder:
        """Map a Billbee-internal order to the generic OmsOrder."""
        return OmsOrder(
            order_id=str(order.billbee_order_id),
            order_number=order.order_number,
            invoice_number=order.invoice_number,
            invoice_number_prefix=order.invoice_number_prefix,
            state=order.state,
            created_at=order.created_at,
            total_cost=order.total_cost,
            currency=order.currency,
            customer_name=order.customer_name,
            customer_email=order.customer_email,
            shop_id=order.shop_id,
            shop_name=order.shop_name,
            platform=order.platform,
            items=[self._to_oms_order_item(item) for item in order.items],
            tags=order.tags,
            paid_amount=order.paid_amount,
            is_paid=order.is_paid,
            paid_at=order.paid_at,
            tax_rate_1=order.tax_rate_1,
            tax_rate_2=order.tax_rate_2,
        )

    async def fetch_orders(
        self,
        store_ids: list[int] | None = None,
        min_date: datetime | None = None,
        max_date: datetime | None = None,
    ) -> list[OmsOrder]:
        """Fetch orders from the Billbee API (paginated, rate-limited) and map to OmsOrder."""
        page_size = 250
        params: dict[str, str | int | float | None] = {"pageSize": page_size}
        if min_date:
            params["minOrderDate"] = min_date.isoformat()
        if max_date:
            params["maxOrderDate"] = max_date.isoformat()
        store_params: list[tuple[str, str | int | float | None]] = [("storeId", str(store)) for store in (store_ids or [])]

        async def _fetch_pages(http_client: httpx.AsyncClient) -> list[OmsOrder]:
            orders: list[OmsOrder] = []
            page = 1
            while True:
                params["page"] = page
                data = await _make_billbee_request(
                    http_client,
                    f"{BILLBEE_API_BASE}/orders",
                    list(params.items()) + store_params,
                    self._headers,
                    self._auth,
                )
                for order_data in data.get("Data", []):
                    orders.append(self._to_oms_order(_parse_billbee_order(order_data)))

                paging = data.get("Paging", {})
                if page >= paging.get("TotalPages", 1):
                    break
                page += 1
                # Rate limiting: max 2 requests/second
                await asyncio.sleep(0.5)
            return orders

        async with httpx.AsyncClient() as client:
            return await _fetch_pages(client)

    async def fetch_orders_cached(
        self,
        store_ids: list[int] | None = None,
        min_date: datetime | None = None,
        max_date: datetime | None = None,
        force_refresh: bool = False,
    ) -> tuple[list[OmsOrder], bool, datetime | None]:
        """Fetch orders with 2-hour caching (tenant-wide). Caching is provider-internal (D-4)."""
        cache_key = _get_cache_key(store_ids, min_date, max_date)

        if not force_refresh and cache_key in _order_cache:
            entry = _order_cache[cache_key]
            if entry.expires_at > datetime.now(UTC):
                return entry.data, True, entry.expires_at

        orders = await self.fetch_orders(store_ids=store_ids, min_date=min_date, max_date=max_date)
        expires_at = datetime.now(UTC) + CACHE_DURATION
        _order_cache[cache_key] = _CacheEntry(data=orders, expires_at=expires_at)
        return orders, False, expires_at

    async def fetch_order_by_id(self, order_id: str) -> OmsOrder | None:
        """Fetch a single order by its (Billbee) order ID."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BILLBEE_API_BASE}/orders/{order_id}",
                headers=self._headers,
                auth=self._auth,
                timeout=30.0,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            return self._to_oms_order(_parse_billbee_order(data.get("Data", {})))

    async def fetch_invoice_pdf(self, order_id: str) -> tuple[bytes | None, str | None]:
        """Fetch invoice PDF via GET (read-only). Returns (pdf_bytes, error_message)."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{BILLBEE_API_BASE}/orders/{order_id}",
                    params={"includeInvoicePdf": "true"},
                    headers=self._headers,
                    auth=self._auth,
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

                pdf_data = data.get("Data", {}).get("PdfData")
                if not pdf_data:
                    return None, "PDF not available in Billbee (PdfData null)"

                try:
                    return base64.b64decode(pdf_data), None
                except binascii.Error as decode_error:
                    return None, f"PDF decode failed: corrupted Base64 data ({decode_error})"
            except httpx.TimeoutException:
                return None, "PDF fetch failed: timeout after 30s"
            except httpx.HTTPStatusError as error:
                return None, f"PDF fetch failed: HTTP {error.response.status_code}"
            except httpx.RequestError as error:
                return None, f"PDF fetch failed: {type(error).__name__}"

    async def set_labels(self, order_ids: list[str], label: str) -> tuple[int, list[str]]:
        """Set a label on multiple orders in bulk. Returns (success_count, errors)."""
        if not order_ids:
            return 0, []

        batch_size = 100
        success_count = 0
        errors: list[str] = []
        numeric_ids = [int(order_id) for order_id in order_ids]

        async def _set_labels_batch(http_client: httpx.AsyncClient, batch_ids: list[int]) -> bool:
            try:
                await _make_billbee_request(
                    http_client,
                    f"{BILLBEE_API_BASE}/orders/tags",
                    [],
                    self._headers,
                    self._auth,
                    method="POST",
                    json_body={"OrderIds": batch_ids, "Tags": [label]},
                )
                return True
            except Exception as error:
                errors.append(f"Label batch failed ({len(batch_ids)} orders): {error}")
                return False

        async with httpx.AsyncClient() as client:
            for start in range(0, len(numeric_ids), batch_size):
                batch = numeric_ids[start : start + batch_size]
                if await _set_labels_batch(client, batch):
                    success_count += len(batch)

        return success_count, errors

    def enrich_transaction(self, order: OmsOrder) -> EnrichmentResult:
        """Extract enrichment data from a matched OMS order."""
        invoice_number = None
        if order.invoice_number:
            prefix = order.invoice_number_prefix or ""
            invoice_number = f"{prefix}{order.invoice_number}"

        order_date = order.paid_at or (order.created_at.date() if order.created_at else None)

        return EnrichmentResult(
            oms_order_id=order.order_id,
            invoice_number=invoice_number,
            shop_name=order.shop_name,
            platform=order.platform,
            customer_name=order.customer_name or None,
            order_date=order_date,
        )


def clear_cache() -> int:
    """Clear the tenant-wide order cache. Returns number of entries cleared."""
    count = len(_order_cache)
    _order_cache.clear()
    return count
