"""Tests for provider-agnostic OMS transaction-to-order matching."""

from datetime import datetime
from decimal import Decimal

import pytest
from app.services.oms_matching import (
    build_order_lookup,
    find_matching_orders,
    match_transaction_to_order,
)
from app.services.oms_provider import OmsOrder, OmsOrderItem


def _make_order(
    *,
    order_id: str,
    order_number: str,
    total_cost: Decimal,
    created_at: datetime,
    customer_name: str,
    customer_email: str | None = None,
) -> OmsOrder:
    return OmsOrder(
        order_id=order_id,
        order_number=order_number,
        invoice_number=None,
        invoice_number_prefix=None,
        state=3,
        created_at=created_at,
        total_cost=total_cost,
        currency="EUR",
        customer_name=customer_name,
        customer_email=customer_email,
        shop_id=100,
        shop_name="Test Store",
        platform="Etsy",
        items=[
            OmsOrderItem(
                product_title="Handmade Mug",
                quantity=2,
                total_price=total_cost,
                sku="MUG-001",
                tax_index=1,
                tax_amount=Decimal("0"),
            )
        ],
        tags=["paid"],
        paid_amount=total_cost,
        is_paid=True,
        paid_at=None,
        tax_rate_1=None,
        tax_rate_2=None,
    )


@pytest.fixture
def sample_orders() -> list[OmsOrder]:
    """Create sample OMS orders for testing."""
    return [
        _make_order(
            order_id="1001",
            order_number="ET-12345",
            total_cost=Decimal("49.99"),
            created_at=datetime(2026, 2, 15, 10, 30),
            customer_name="Max Mustermann",
            customer_email="max@example.com",
        ),
        _make_order(
            order_id="1002",
            order_number="AM-67890",
            total_cost=Decimal("129.00"),
            created_at=datetime(2026, 2, 14, 14, 0),
            customer_name="Erika Musterfrau",
            customer_email="erika@example.com",
        ),
    ]


class TestFindMatchingOrders:
    """Tests for find_matching_orders function."""

    def should_match_exact_amount(self, sample_orders: list[OmsOrder]):
        """Exact amount match should have highest confidence."""
        matches = find_matching_orders(
            orders=sample_orders,
            amount=Decimal("49.99"),
            transaction_date=datetime(2026, 2, 15),
        )

        assert len(matches) >= 1
        assert matches[0].oms_order_id == "1001"
        assert "Exact amount match" in matches[0].match_reasons
        assert matches[0].confidence >= 0.5

    def should_match_amount_within_tolerance(self, sample_orders: list[OmsOrder]):
        """Amount within €0.10 should still match."""
        matches = find_matching_orders(
            orders=sample_orders,
            amount=Decimal("49.95"),
            transaction_date=datetime(2026, 2, 15),
        )

        assert len(matches) >= 1
        assert any(match.oms_order_id == "1001" for match in matches)

    def should_boost_confidence_for_same_date(self, sample_orders: list[OmsOrder]):
        """Same date should boost confidence."""
        matches = find_matching_orders(
            orders=sample_orders,
            amount=Decimal("49.99"),
            transaction_date=datetime(2026, 2, 15),
        )

        assert len(matches) >= 1
        assert matches[0].oms_order_id == "1001"
        assert "Same date" in matches[0].match_reasons

    def should_boost_confidence_for_counterparty_match(self, sample_orders: list[OmsOrder]):
        """Counterparty name match should boost confidence."""
        matches = find_matching_orders(
            orders=sample_orders,
            amount=Decimal("49.99"),
            transaction_date=datetime(2026, 2, 15),
            counterparty="Mustermann",
        )

        assert len(matches) >= 1
        assert matches[0].oms_order_id == "1001"
        assert "Customer name matches counterparty" in matches[0].match_reasons

    def should_sort_by_confidence_descending(self, sample_orders: list[OmsOrder]):
        """Results should be sorted by confidence (highest first)."""
        matches = find_matching_orders(
            orders=sample_orders,
            amount=Decimal("100.00"),  # Neither order matches exactly
            transaction_date=datetime(2026, 2, 14),
        )

        if len(matches) >= 2:
            assert matches[0].confidence >= matches[1].confidence

    def should_exclude_no_match_orders(self, sample_orders: list[OmsOrder]):
        """Orders with no match criteria should not be included with high confidence."""
        matches = find_matching_orders(
            orders=sample_orders,
            amount=Decimal("999.99"),  # No order has this amount
            transaction_date=datetime(2026, 1, 1),  # Too far from any order date
        )

        for match in matches:
            assert match.confidence < 0.5


class TestBuildOrderLookup:
    """Tests for build_order_lookup function."""

    def should_index_by_order_number(self, sample_orders: list[OmsOrder]):
        by_order_number, _ = build_order_lookup(sample_orders)

        assert by_order_number["ET-12345"].order_id == "1001"
        assert by_order_number["AM-67890"].order_id == "1002"

    def should_index_by_lowercased_email(self, sample_orders: list[OmsOrder]):
        _, by_email = build_order_lookup(sample_orders)

        assert by_email["max@example.com"].order_id == "1001"
        assert by_email["erika@example.com"].order_id == "1002"

    def should_store_both_prefixed_and_stripped_order_numbers(self):
        """Shopify-style '#3703' should also be indexed under '3703'."""
        order = _make_order(
            order_id="3703",
            order_number="#3703",
            total_cost=Decimal("10.00"),
            created_at=datetime(2026, 2, 1),
            customer_name="Test",
        )
        by_order_number, _ = build_order_lookup([order])

        assert by_order_number["#3703"].order_id == "3703"
        assert by_order_number["3703"].order_id == "3703"


class TestMatchTransactionToOrder:
    """Tests for match_transaction_to_order function."""

    def should_match_by_order_number(self, sample_orders: list[OmsOrder]):
        by_order_number, by_email = build_order_lookup(sample_orders)

        match = match_transaction_to_order(
            order_number_lookup=by_order_number,
            email_lookup=by_email,
            match_strategy="order_number",
            source_reference="ET-12345",
        )

        assert match is not None
        assert match.order_id == "1001"

    def should_match_by_email(self, sample_orders: list[OmsOrder]):
        by_order_number, by_email = build_order_lookup(sample_orders)

        match = match_transaction_to_order(
            order_number_lookup=by_order_number,
            email_lookup=by_email,
            match_strategy="email",
            counterparty="ERIKA@EXAMPLE.COM",
        )

        assert match is not None
        assert match.order_id == "1002"

    def should_strip_shopify_hash_prefix(self):
        """A reference '#3703' should match an order_number '3703' and vice versa."""
        order = _make_order(
            order_id="3703",
            order_number="3703",
            total_cost=Decimal("10.00"),
            created_at=datetime(2026, 2, 1),
            customer_name="Test",
        )
        by_order_number, by_email = build_order_lookup([order])

        match = match_transaction_to_order(
            order_number_lookup=by_order_number,
            email_lookup=by_email,
            match_strategy="order_number",
            source_reference="#3703",
        )

        assert match is not None
        assert match.order_id == "3703"

    def should_extract_order_number_from_etsy_reference(self, sample_orders: list[OmsOrder]):
        """Etsy 'Payment for Order #ET-12345' style references should resolve."""
        by_order_number, by_email = build_order_lookup(sample_orders)

        match = match_transaction_to_order(
            order_number_lookup=by_order_number,
            email_lookup=by_email,
            match_strategy="order_number",
            source_reference="Payment for Order #ET-12345",
        )

        assert match is not None
        assert match.order_id == "1001"

    def should_return_none_when_no_match(self, sample_orders: list[OmsOrder]):
        by_order_number, by_email = build_order_lookup(sample_orders)

        match = match_transaction_to_order(
            order_number_lookup=by_order_number,
            email_lookup=by_email,
            match_strategy="order_number",
            source_reference="UNKNOWN-999",
        )

        assert match is None
