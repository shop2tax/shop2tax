"""Tests for the BillbeeProvider (cache, parsing, API calls, OmsOrder mapping)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from app.models.oms_provider import OmsProviderType
from app.services.oms_provider import OmsOrder, OmsOrderItem, OmsProvider
from app.services.providers.billbee import (
    CACHE_DURATION,
    BillbeeProvider,
    _CacheEntry,
    _get_cache_key,
    _order_cache,
    _parse_billbee_order,
    clear_cache,
)


def _make_provider() -> BillbeeProvider:
    return BillbeeProvider(api_key="k", username="user", password="pass")


# --- _get_cache_key ---


class TestGetCacheKey:
    def should_generate_key_without_store_ids(self):
        assert _get_cache_key(None, None, None) == "all"

    def should_generate_key_with_empty_store_ids(self):
        assert _get_cache_key([], None, None) == "all"

    def should_generate_key_with_single_store_id(self):
        assert _get_cache_key([42], None, None) == "42"

    def should_generate_key_with_multiple_store_ids_sorted(self):
        assert _get_cache_key([99, 10, 55], None, None) == "10,55,99"

    def should_generate_different_keys_for_different_store_ids(self):
        assert _get_cache_key([1], None, None) != _get_cache_key([2], None, None)

    def should_include_date_range_in_key(self):
        min_date = datetime(2026, 1, 1, tzinfo=UTC)
        max_date = datetime(2026, 2, 1, tzinfo=UTC)
        key = _get_cache_key([5], min_date, max_date)
        assert "5" in key
        assert min_date.isoformat() in key
        assert max_date.isoformat() in key


# --- _parse_billbee_order ---


EXAMPLE_RAW_ORDER = {
    "BillBeeOrderId": 5001,
    "OrderNumber": "ET-99999",
    "State": 3,
    "CreatedAt": "2026-01-10T12:00:00+00:00",
    "TotalCost": 59.90,
    "Currency": "EUR",
    "Buyer": {
        "FirstName": "Anna",
        "LastName": "Schmidt",
        "Email": "anna@example.com",
    },
    "Seller": {
        "BillbeeShopId": 200,
        "BillbeeShopName": "My Etsy",
        "Platform": "Etsy",
    },
    "OrderItems": [
        {
            "BillbeeId": 7001,
            "Product": {"Title": "Ceramic Bowl", "SKU": "BOWL-01"},
            "Quantity": 3,
            "TotalPrice": 59.90,
        }
    ],
    "InvoiceAddress": {
        "FirstName": "Anna",
        "LastName": "Schmidt",
        "Company": "Keramik GmbH",
        "Street": "Hauptstr.",
        "HouseNumber": "12",
        "Zip": "10115",
        "City": "Berlin",
        "Country": "DE",
        "Email": "anna@example.com",
    },
    "Tags": ["priority", "new"],
    "PaidAmount": 59.90,
}


class TestParseBillbeeOrder:
    def should_parse_complete_order(self):
        order = _parse_billbee_order(EXAMPLE_RAW_ORDER)

        assert order.billbee_order_id == 5001
        assert order.order_number == "ET-99999"
        assert order.state == 3
        assert order.created_at == datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
        assert order.total_cost == Decimal("59.9")
        assert order.currency == "EUR"
        assert order.customer_name == "Anna Schmidt"
        assert order.customer_email == "anna@example.com"
        assert order.shop_id == 200
        assert order.shop_name == "My Etsy"
        assert order.platform == "Etsy"
        assert order.tags == ["priority", "new"]
        assert order.paid_amount == Decimal("59.9")
        assert order.is_paid is True

    def should_parse_order_items(self):
        order = _parse_billbee_order(EXAMPLE_RAW_ORDER)

        assert len(order.items) == 1
        item = order.items[0]
        assert item.billbee_id == 7001
        assert item.product_title == "Ceramic Bowl"
        assert item.quantity == 3
        assert item.total_price == Decimal("59.9")
        assert item.sku == "BOWL-01"

    def should_parse_invoice_address(self):
        order = _parse_billbee_order(EXAMPLE_RAW_ORDER)

        assert order.invoice_address is not None
        address = order.invoice_address
        assert address.first_name == "Anna"
        assert address.last_name == "Schmidt"
        assert address.company == "Keramik GmbH"
        assert address.street == "Hauptstr."
        assert address.house_number == "12"
        assert address.zip_code == "10115"
        assert address.city == "Berlin"
        assert address.country == "DE"
        assert address.email == "anna@example.com"

    def should_handle_missing_invoice_address(self):
        data = {**EXAMPLE_RAW_ORDER, "InvoiceAddress": None}
        order = _parse_billbee_order(data)
        assert order.invoice_address is None

    def should_handle_no_invoice_address_key(self):
        data = {k: v for k, v in EXAMPLE_RAW_ORDER.items() if k != "InvoiceAddress"}
        order = _parse_billbee_order(data)
        assert order.invoice_address is None

    def should_handle_empty_order_items(self):
        data = {**EXAMPLE_RAW_ORDER, "OrderItems": []}
        order = _parse_billbee_order(data)
        assert order.items == []

    def should_handle_missing_buyer_names_with_fullname_fallback(self):
        data = {**EXAMPLE_RAW_ORDER, "Buyer": {"FullName": "Max Power"}}
        order = _parse_billbee_order(data)
        assert order.customer_name == "Max Power"

    def should_detect_unpaid_order(self):
        data = {**EXAMPLE_RAW_ORDER, "PaidAmount": 0, "TotalCost": 59.90}
        order = _parse_billbee_order(data)
        assert order.is_paid is False

    def should_handle_missing_product_fields(self):
        data = {
            **EXAMPLE_RAW_ORDER,
            "OrderItems": [{"BillbeeId": 1, "Product": {}, "Quantity": 1, "TotalPrice": 10}],
        }
        order = _parse_billbee_order(data)
        assert order.items[0].product_title == "Unknown"
        assert order.items[0].sku is None

    def should_parse_tax_rate_fields_from_order(self):
        order_data = {
            "BillBeeOrderId": 12345,
            "OrderNumber": "ET-001",
            "State": 3,
            "CreatedAt": "2026-02-15T10:00:00Z",
            "TotalCost": 119.00,
            "Currency": "EUR",
            "Buyer": {"FirstName": "Max", "LastName": "Mustermann"},
            "Seller": {"BillbeeShopId": 100, "BillbeeShopName": "Test Shop"},
            "Tags": [],
            "PaidAmount": 119.00,
            "OrderItems": [],
            "TaxRate1": 19.0,
            "TaxRate2": 7.0,
        }
        order = _parse_billbee_order(order_data)
        assert order.tax_rate_1 == Decimal("19")
        assert order.tax_rate_2 == Decimal("7")

    def should_parse_tax_index_from_order_items(self):
        order_data = {
            "BillBeeOrderId": 12345,
            "OrderNumber": "ET-002",
            "State": 3,
            "CreatedAt": "2026-02-15T10:00:00Z",
            "TotalCost": 200.00,
            "Currency": "EUR",
            "Buyer": {"FirstName": "Erika", "LastName": "Musterfrau"},
            "Seller": {"BillbeeShopId": 100},
            "Tags": [],
            "PaidAmount": 200.00,
            "TaxRate1": 19.0,
            "TaxRate2": 7.0,
            "OrderItems": [
                {
                    "BillbeeId": 1,
                    "Product": {"Title": "Widget 19%", "SKU": "W19"},
                    "Quantity": 1,
                    "TotalPrice": 119.00,
                    "TaxIndex": 1,
                    "TaxAmount": 19.00,
                },
                {
                    "BillbeeId": 2,
                    "Product": {"Title": "Book 7%", "SKU": "B7"},
                    "Quantity": 1,
                    "TotalPrice": 81.00,
                    "TaxIndex": 2,
                    "TaxAmount": 5.67,
                },
            ],
        }
        order = _parse_billbee_order(order_data)
        assert len(order.items) == 2
        assert order.items[0].tax_index == 1
        assert order.items[0].tax_amount == Decimal("19")
        assert order.items[1].tax_index == 2
        assert order.items[1].tax_amount == Decimal("5.67")

    def should_default_tax_index_to_1_when_missing(self):
        order_data = {
            "BillBeeOrderId": 12345,
            "OrderNumber": "ET-003",
            "State": 3,
            "CreatedAt": "2026-02-15T10:00:00Z",
            "TotalCost": 50.00,
            "Currency": "EUR",
            "Buyer": {"FirstName": "Test", "LastName": "User"},
            "Seller": {"BillbeeShopId": 100},
            "Tags": [],
            "PaidAmount": 50.00,
            "OrderItems": [
                {
                    "BillbeeId": 1,
                    "Product": {"Title": "Item without TaxIndex"},
                    "Quantity": 1,
                    "TotalPrice": 50.00,
                },
            ],
        }
        order = _parse_billbee_order(order_data)
        assert len(order.items) == 1
        assert order.items[0].tax_index == 1
        assert order.items[0].tax_amount == Decimal("0")

    def should_handle_null_tax_rates(self):
        order_data = {
            "BillBeeOrderId": 12345,
            "OrderNumber": "ET-004",
            "State": 3,
            "CreatedAt": "2026-02-15T10:00:00Z",
            "TotalCost": 50.00,
            "Currency": "EUR",
            "Buyer": {"FirstName": "Test", "LastName": "User"},
            "Seller": {"BillbeeShopId": 100},
            "Tags": [],
            "PaidAmount": 50.00,
            "OrderItems": [],
        }
        order = _parse_billbee_order(order_data)
        assert order.tax_rate_1 is None
        assert order.tax_rate_2 is None


# --- Protocol conformance + OmsOrder mapping ---


class TestProviderConformance:
    def should_satisfy_oms_provider_protocol(self):
        provider = _make_provider()
        assert isinstance(provider, OmsProvider)

    def should_expose_provider_type_and_display_name(self):
        provider = BillbeeProvider(api_key="k", username="u", password="p", display_name="My Billbee")
        assert provider.provider_type == OmsProviderType.BILLBEE
        assert provider.display_name == "My Billbee"


class TestToOmsOrder:
    def should_map_billbee_order_to_oms_order(self):
        billbee_order = _parse_billbee_order(EXAMPLE_RAW_ORDER)
        oms_order = _make_provider()._to_oms_order(billbee_order)

        assert isinstance(oms_order, OmsOrder)
        assert oms_order.order_id == "5001"  # str of billbee_order_id
        assert oms_order.order_number == "ET-99999"
        assert oms_order.invoice_number == billbee_order.invoice_number
        assert oms_order.invoice_number_prefix == billbee_order.invoice_number_prefix
        assert oms_order.state == 3
        assert oms_order.created_at == datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
        assert oms_order.total_cost == Decimal("59.9")
        assert oms_order.currency == "EUR"
        assert oms_order.customer_name == "Anna Schmidt"
        assert oms_order.customer_email == "anna@example.com"
        assert oms_order.shop_id == 200
        assert oms_order.shop_name == "My Etsy"
        assert oms_order.platform == "Etsy"
        assert oms_order.tags == ["priority", "new"]
        assert oms_order.paid_amount == Decimal("59.9")
        assert oms_order.is_paid is True
        assert oms_order.paid_at == billbee_order.paid_at
        assert oms_order.tax_rate_1 == billbee_order.tax_rate_1
        assert oms_order.tax_rate_2 == billbee_order.tax_rate_2

    def should_map_order_items(self):
        billbee_order = _parse_billbee_order(EXAMPLE_RAW_ORDER)
        oms_order = _make_provider()._to_oms_order(billbee_order)

        assert len(oms_order.items) == 1
        item = oms_order.items[0]
        assert isinstance(item, OmsOrderItem)
        assert item.product_title == "Ceramic Bowl"
        assert item.quantity == 3
        assert item.total_price == Decimal("59.9")
        assert item.sku == "BOWL-01"
        assert item.tax_index == 1
        assert item.tax_amount == Decimal("0")


# --- Helper: build mock httpx response ---


def _make_orders_api_response(orders_data: list[dict], page: int = 1, total_pages: int = 1):
    return {
        "Data": orders_data,
        "Paging": {"Page": page, "TotalPages": total_pages},
    }


def _make_mock_response(json_data: dict, status_code: int = 200):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=MagicMock(), response=response)
    return response


def _patch_httpx_client(responses: list):
    """Create a patched httpx.AsyncClient context manager that returns responses in sequence."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=responses)
    mock_context = AsyncMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_client)
    mock_context.__aexit__ = AsyncMock(return_value=False)
    return mock_context, mock_client


# --- fetch_orders ---


class TestFetchOrders:
    @pytest.mark.asyncio
    async def should_fetch_single_page_of_orders(self):
        api_response = _make_orders_api_response([EXAMPLE_RAW_ORDER], page=1, total_pages=1)
        response = _make_mock_response(api_response)
        mock_context, _ = _patch_httpx_client([response])

        with patch("httpx.AsyncClient", return_value=mock_context):
            orders = await _make_provider().fetch_orders()

        assert len(orders) == 1
        assert isinstance(orders[0], OmsOrder)
        assert orders[0].order_id == "5001"

    @pytest.mark.asyncio
    async def should_paginate_through_multiple_pages(self):
        page1_response = _make_mock_response(_make_orders_api_response([EXAMPLE_RAW_ORDER], page=1, total_pages=2))
        second_order = {
            **EXAMPLE_RAW_ORDER,
            "BillBeeOrderId": 5002,
            "OrderNumber": "ET-11111",
        }
        page2_response = _make_mock_response(_make_orders_api_response([second_order], page=2, total_pages=2))
        mock_context, mock_client = _patch_httpx_client([page1_response, page2_response])

        with patch("httpx.AsyncClient", return_value=mock_context):
            orders = await _make_provider().fetch_orders()

        assert len(orders) == 2
        assert orders[0].order_id == "5001"
        assert orders[1].order_id == "5002"
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def should_pass_store_ids_as_params(self):
        response = _make_mock_response(_make_orders_api_response([], page=1, total_pages=1))
        mock_context, mock_client = _patch_httpx_client([response])

        with patch("httpx.AsyncClient", return_value=mock_context):
            await _make_provider().fetch_orders(store_ids=[10, 20])

        params = mock_client.get.call_args.kwargs["params"]
        assert ("storeId", "10") in params
        assert ("storeId", "20") in params

    @pytest.mark.asyncio
    async def should_pass_optional_date_filters(self):
        response = _make_mock_response(_make_orders_api_response([], page=1, total_pages=1))
        mock_context, mock_client = _patch_httpx_client([response])

        min_date = datetime(2026, 1, 1, tzinfo=UTC)
        max_date = datetime(2026, 2, 1, tzinfo=UTC)

        with patch("httpx.AsyncClient", return_value=mock_context):
            await _make_provider().fetch_orders(min_date=min_date, max_date=max_date)

        params_dict = dict(mock_client.get.call_args.kwargs["params"])
        assert params_dict["minOrderDate"] == min_date.isoformat()
        assert params_dict["maxOrderDate"] == max_date.isoformat()


# --- fetch_orders_cached ---


class TestFetchOrdersCached:
    def setup_method(self):
        _order_cache.clear()

    def teardown_method(self):
        _order_cache.clear()

    @pytest.mark.asyncio
    async def should_return_cached_data_on_cache_hit(self):
        cached_order = _make_provider()._to_oms_order(_parse_billbee_order(EXAMPLE_RAW_ORDER))
        _order_cache["all"] = _CacheEntry(
            data=[cached_order],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

        orders, is_cached, _ = await _make_provider().fetch_orders_cached()

        assert is_cached is True
        assert len(orders) == 1
        assert orders[0].order_id == "5001"

    @pytest.mark.asyncio
    async def should_fetch_fresh_on_cache_miss(self):
        response = _make_mock_response(_make_orders_api_response([EXAMPLE_RAW_ORDER], page=1, total_pages=1))
        mock_context, _ = _patch_httpx_client([response])

        with patch("httpx.AsyncClient", return_value=mock_context):
            orders, is_cached, _ = await _make_provider().fetch_orders_cached()

        assert is_cached is False
        assert len(orders) == 1
        assert "all" in _order_cache

    @pytest.mark.asyncio
    async def should_bypass_cache_on_force_refresh(self):
        cached_order = _make_provider()._to_oms_order(_parse_billbee_order(EXAMPLE_RAW_ORDER))
        _order_cache["all"] = _CacheEntry(
            data=[cached_order],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

        response = _make_mock_response(_make_orders_api_response([EXAMPLE_RAW_ORDER], page=1, total_pages=1))
        mock_context, _ = _patch_httpx_client([response])

        with patch("httpx.AsyncClient", return_value=mock_context):
            _, is_cached, _ = await _make_provider().fetch_orders_cached(force_refresh=True)

        assert is_cached is False

    @pytest.mark.asyncio
    async def should_refetch_when_cache_expired(self):
        cached_order = _make_provider()._to_oms_order(_parse_billbee_order(EXAMPLE_RAW_ORDER))
        _order_cache["all"] = _CacheEntry(
            data=[cached_order],
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        response = _make_mock_response(_make_orders_api_response([EXAMPLE_RAW_ORDER], page=1, total_pages=1))
        mock_context, _ = _patch_httpx_client([response])

        with patch("httpx.AsyncClient", return_value=mock_context):
            _, is_cached, _ = await _make_provider().fetch_orders_cached()

        assert is_cached is False

    @pytest.mark.asyncio
    async def should_use_store_ids_in_cache_key(self):
        response = _make_mock_response(_make_orders_api_response([], page=1, total_pages=1))
        mock_context, _ = _patch_httpx_client([response])

        with patch("httpx.AsyncClient", return_value=mock_context):
            await _make_provider().fetch_orders_cached(store_ids=[5, 10])

        assert "5,10" in _order_cache

    @pytest.mark.asyncio
    async def should_set_cache_expiry_in_future(self):
        response = _make_mock_response(_make_orders_api_response([], page=1, total_pages=1))
        mock_context, _ = _patch_httpx_client([response])

        before = datetime.now(UTC)
        with patch("httpx.AsyncClient", return_value=mock_context):
            _, _, expires_at = await _make_provider().fetch_orders_cached()

        assert expires_at >= before + CACHE_DURATION - timedelta(seconds=5)

    @pytest.mark.asyncio
    async def should_store_oms_orders_in_cache(self):
        response = _make_mock_response(_make_orders_api_response([EXAMPLE_RAW_ORDER], page=1, total_pages=1))
        mock_context, _ = _patch_httpx_client([response])

        with patch("httpx.AsyncClient", return_value=mock_context):
            await _make_provider().fetch_orders_cached()

        cached = _order_cache["all"].data
        assert len(cached) == 1
        assert isinstance(cached[0], OmsOrder)


# --- fetch_order_by_id ---


class TestFetchOrderById:
    @pytest.mark.asyncio
    async def should_return_order_on_success(self):
        response = _make_mock_response({"Data": EXAMPLE_RAW_ORDER})
        mock_context, _ = _patch_httpx_client([response])

        with patch("httpx.AsyncClient", return_value=mock_context):
            order = await _make_provider().fetch_order_by_id("5001")

        assert order is not None
        assert isinstance(order, OmsOrder)
        assert order.order_id == "5001"

    @pytest.mark.asyncio
    async def should_return_none_on_404(self):
        response = MagicMock(spec=httpx.Response)
        response.status_code = 404
        response.raise_for_status = MagicMock()
        mock_context, _ = _patch_httpx_client([response])

        with patch("httpx.AsyncClient", return_value=mock_context):
            order = await _make_provider().fetch_order_by_id("99999")

        assert order is None


# --- clear_cache ---


class TestClearCache:
    def setup_method(self):
        _order_cache.clear()

    def teardown_method(self):
        _order_cache.clear()

    def should_clear_all_entries(self):
        _order_cache["all"] = _CacheEntry(data=[], expires_at=datetime.now(UTC))
        _order_cache["5,10"] = _CacheEntry(data=[], expires_at=datetime.now(UTC))

        count = clear_cache()

        assert count == 2
        assert len(_order_cache) == 0

    def should_return_zero_when_no_entries_exist(self):
        count = clear_cache()
        assert count == 0
        assert len(_order_cache) == 0


# --- fetch_invoice_pdf (Billbee internal HTTP) ---


def _patch_async_client(handler):
    """Patch httpx.AsyncClient with a MockTransport-backed client."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        return real_async_client(transport=transport)

    return patch("httpx.AsyncClient", _factory)


class TestFetchInvoicePdf:
    @pytest.mark.asyncio
    async def should_fetch_pdf_via_get_endpoint(self):
        """PDF fetch must use GET /orders/{id}?includeInvoicePdf=true."""
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            return httpx.Response(200, json={"Data": {"PdfData": "dGVzdA=="}})  # base64 "test"

        with _patch_async_client(handler):
            pdf_bytes, error = await _make_provider().fetch_invoice_pdf("12345")

        assert pdf_bytes == b"test"
        assert error is None
        assert "/orders/12345" in captured["url"]
        assert "includeInvoicePdf=true" in captured["url"]
        assert captured["method"] == "GET"

    @pytest.mark.asyncio
    async def should_report_http_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "server"})

        with _patch_async_client(handler):
            pdf_bytes, error = await _make_provider().fetch_invoice_pdf("12345")

        assert pdf_bytes is None
        assert error is not None
        assert "HTTP 500" in error

    @pytest.mark.asyncio
    async def should_report_null_pdf_data_as_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"Data": {"PdfData": None}})

        with _patch_async_client(handler):
            pdf_bytes, error = await _make_provider().fetch_invoice_pdf("12345")

        assert pdf_bytes is None
        assert error is not None
        assert "PdfData null" in error

    @pytest.mark.asyncio
    async def should_handle_corrupted_base64_pdf_data(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"Data": {"PdfData": "!!!invalid-base64!!!"}})

        with _patch_async_client(handler):
            pdf_bytes, error = await _make_provider().fetch_invoice_pdf("12345")

        assert pdf_bytes is None
        assert error is not None
        assert "decode failed" in error.lower() or "Base64" in error

    @pytest.mark.asyncio
    async def should_handle_network_error_without_crashing(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("DNS resolution failed")

        with _patch_async_client(handler):
            pdf_bytes, error = await _make_provider().fetch_invoice_pdf("12345")

        assert pdf_bytes is None
        assert error is not None
        assert "ConnectError" in error


# --- set_labels (Billbee bulk label endpoint) ---


class TestSetLabels:
    @pytest.mark.asyncio
    async def should_use_bulk_endpoint_for_labels(self):
        """Labels must be set via a single POST /orders/tags, not N+1 calls."""
        import json as json_module

        captured_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(200, json={"ErrorCode": 0})

        with _patch_async_client(handler):
            success_count, errors = await _make_provider().set_labels(["1", "2", "3", "4", "5"], "shop2tax")

        assert len(captured_requests) == 1
        assert captured_requests[0].method == "POST"
        assert "/orders/tags" in str(captured_requests[0].url)
        body = json_module.loads(captured_requests[0].content)
        assert body["OrderIds"] == [1, 2, 3, 4, 5]
        assert body["Tags"] == ["shop2tax"]
        assert success_count == 5
        assert errors == []

    @pytest.mark.asyncio
    async def should_chunk_bulk_labels_in_batches(self):
        """Over 100 orders should be split into multiple bulk calls."""
        import json as json_module

        captured_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(200, json={"ErrorCode": 0})

        with _patch_async_client(handler):
            success_count, _ = await _make_provider().set_labels([str(i) for i in range(1, 151)], "shop2tax")

        assert len(captured_requests) == 2
        body_0 = json_module.loads(captured_requests[0].content)
        body_1 = json_module.loads(captured_requests[1].content)
        assert len(body_0["OrderIds"]) == 100
        assert len(body_1["OrderIds"]) == 50
        assert success_count == 150

    @pytest.mark.asyncio
    async def should_return_empty_on_no_order_ids(self):
        success_count, errors = await _make_provider().set_labels([], "shop2tax")
        assert success_count == 0
        assert errors == []


# --- _make_billbee_request retry behavior ---


class TestRetryBehavior:
    @pytest.mark.asyncio
    async def should_retry_on_429_with_retry_after_header(self, monkeypatch):
        """429 response should parse Retry-After header and retry."""
        from app.services.providers import billbee as billbee_module

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                mock_response = MagicMock()
                mock_response.status_code = 429
                mock_response.headers = {"Retry-After": "1"}
                raise httpx.HTTPStatusError("Rate limited", request=MagicMock(), response=mock_response)
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {"Data": []}
            return mock_response

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = mock_get

        monkeypatch.setattr(billbee_module.asyncio, "sleep", AsyncMock())

        result = await billbee_module._make_billbee_request(
            mock_client,
            "https://app.billbee.io/api/v1/test",
            [],
            {"X-Billbee-Api-Key": "test-key"},
            ("user", "pass"),
            method="GET",
        )

        assert call_count == 2
        assert result == {"Data": []}


# --- determine_line_item_accounting ---


class TestDetermineLineItemAccounting:
    """Tests for SKR03/Tax determination logic (pure-logic unit tests).

    Note: SKR03Account.id IS the account number (e.g., 8195, 8400, 8300).
    """

    def should_return_8195_for_small_business(self, seeded_session):
        from app.models.receipt_line_item import TaxRule
        from app.services.receipt_service import determine_line_item_accounting

        skr03_id, tax_rule, tax_rate = determine_line_item_accounting(
            is_small_business=True,
            tax_rate_1=Decimal("19"),
            tax_rate_2=Decimal("7"),
            tax_index=1,
            database=seeded_session,
        )

        assert skr03_id == 8195
        assert tax_rule == TaxRule.NO_TAX
        assert tax_rate == Decimal("0")

    def should_return_8400_for_19_percent(self, seeded_session):
        from app.models.receipt_line_item import TaxRule
        from app.services.receipt_service import determine_line_item_accounting

        skr03_id, tax_rule, tax_rate = determine_line_item_accounting(
            is_small_business=False,
            tax_rate_1=Decimal("19"),
            tax_rate_2=Decimal("7"),
            tax_index=1,
            database=seeded_session,
        )

        assert skr03_id == 8400
        assert tax_rule == TaxRule.TAX_INCLUDED
        assert tax_rate == Decimal("19")

    def should_return_8300_for_7_percent(self, seeded_session):
        from app.models.receipt_line_item import TaxRule
        from app.services.receipt_service import determine_line_item_accounting

        skr03_id, tax_rule, tax_rate = determine_line_item_accounting(
            is_small_business=False,
            tax_rate_1=Decimal("19"),
            tax_rate_2=Decimal("7"),
            tax_index=2,
            database=seeded_session,
        )

        assert skr03_id == 8300
        assert tax_rule == TaxRule.TAX_INCLUDED
        assert tax_rate == Decimal("7")

    def should_default_to_19_when_tax_rate_1_missing(self, seeded_session):
        from app.services.receipt_service import determine_line_item_accounting

        skr03_id, _, tax_rate = determine_line_item_accounting(
            is_small_business=False,
            tax_rate_1=None,
            tax_rate_2=None,
            tax_index=1,
            database=seeded_session,
        )

        assert skr03_id == 8400
        assert tax_rate == Decimal("19")

    def should_default_to_7_when_tax_rate_2_missing(self, seeded_session):
        from app.services.receipt_service import determine_line_item_accounting

        skr03_id, _, tax_rate = determine_line_item_accounting(
            is_small_business=False,
            tax_rate_1=None,
            tax_rate_2=None,
            tax_index=2,
            database=seeded_session,
        )

        assert skr03_id == 8300
        assert tax_rate == Decimal("7")

    def should_ignore_tax_rates_for_small_business(self, seeded_session):
        """Kleinunternehmer always gets 8195/NO_TAX regardless of order tax info."""
        from app.models.receipt_line_item import TaxRule
        from app.services.receipt_service import determine_line_item_accounting

        skr03_id, tax_rule, tax_rate = determine_line_item_accounting(
            is_small_business=True,
            tax_rate_1=Decimal("19"),
            tax_rate_2=Decimal("7"),
            tax_index=2,
            database=seeded_session,
        )

        assert skr03_id == 8195
        assert tax_rule == TaxRule.NO_TAX
        assert tax_rate == Decimal("0")
