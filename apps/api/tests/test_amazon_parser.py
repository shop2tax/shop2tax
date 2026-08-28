"""Tests for Amazon Settlement Report Parser.

Tests cover:
- All 4 transaction types detected correctly (Order, Refund, Transfer, Adjustment)
- Row aggregation by (order-id, transaction-type) — multiple CSV rows → 2 output rows
- Sale + Refund for same order-id → separate rows (NOT netted)
- Settlement-Summary semantic detection (not by row position)
- Amount parsing (German formats: 17,95 = 17.95 EUR)
- Date parsing (ISO + localized formats)
- CSV robustness (encoding detection, tab delimiter)
- SKR03 assignment (Kleinunternehmer vs Regelbesteuert)
- Import hash deduplication
- Currency validation (EUR only)
- Reverse Charge always False (Amazon DE is domestic)
- Promotion handling (reduces sale amount)
- Non-order fees (Storage, Subscriptions without order-id)
"""

from datetime import date
from decimal import Decimal

import pytest
from app.services.amazon_parser import (
    AggregationKey,
    AmazonAmountType,
    AmazonParseError,
    AmazonSettlementParser,
    AmazonTransactionType,
    compute_amazon_import_hash,
    is_settlement_summary_row,
    normalize_headers,
)

# --- Sample Data Fixtures ---


def make_settlement_csv(
    rows: list[dict[str, str]],
    delimiter: str = "\t",
    include_summary: bool = False,
) -> bytes:
    """Build a minimal Amazon Settlement V2 CSV from row dicts.

    Headers: settlement-id, settlement-start-date, settlement-end-date, deposit-date,
    total-amount, currency, transaction-type, order-id, merchant-order-id, adjustment-id,
    shipment-id, marketplace-name, amount-type, amount-description, amount, fulfillment-id,
    posted-date, posted-date-time, order-item-code, merchant-order-item-id,
    merchant-adjustment-item-id, sku, quantity-purchased, promotion-id
    """
    headers = [
        "settlement-id",
        "settlement-start-date",
        "settlement-end-date",
        "deposit-date",
        "total-amount",
        "currency",
        "transaction-type",
        "order-id",
        "merchant-order-id",
        "adjustment-id",
        "shipment-id",
        "marketplace-name",
        "amount-type",
        "amount-description",
        "amount",
        "fulfillment-id",
        "posted-date",
        "posted-date-time",
        "order-item-code",
        "merchant-order-item-id",
        "merchant-adjustment-item-id",
        "sku",
        "quantity-purchased",
        "promotion-id",
    ]

    lines = [delimiter.join(headers)]

    # Add settlement summary row if requested (empty transaction-type, filled total-amount)
    if include_summary:
        summary = {
            "settlement-id": "26579761962",
            "settlement-start-date": "2024-01-01",
            "settlement-end-date": "2024-01-14",
            "deposit-date": "2024-01-16",
            "total-amount": "1234,56",
            "currency": "EUR",
            "transaction-type": "",  # Empty = summary row
            "order-id": "",
        }
        row_values = [summary.get(h, "") for h in headers]
        lines.append(delimiter.join(row_values))

    for row in rows:
        row_values = [row.get(h, "") for h in headers]
        lines.append(delimiter.join(row_values))

    return "\n".join(lines).encode("utf-8")


def make_order_row(
    order_id: str,
    amount_type: str,
    amount_description: str,
    amount: str,
    transaction_type: str = "Order",
    posted_date: str = "2024-01-10",
    currency: str = "EUR",
    settlement_id: str = "26579761962",
) -> dict[str, str]:
    """Create a single CSV row dict for an order."""
    return {
        "settlement-id": settlement_id,
        "settlement-start-date": "2024-01-01",
        "settlement-end-date": "2024-01-14",
        "deposit-date": "2024-01-16",
        "total-amount": "",
        "currency": currency,
        "transaction-type": transaction_type,
        "order-id": order_id,
        "amount-type": amount_type,
        "amount-description": amount_description,
        "amount": amount,
        "posted-date": posted_date,
    }


# --- AmazonTransactionType Tests ---


class TestAmazonTransactionType:
    """Tests for AmazonTransactionType enum and helper methods."""

    def should_identify_revenue_types(self):
        assert AmazonTransactionType.ORDER.is_revenue()
        assert AmazonTransactionType.REFUND.is_revenue()
        assert not AmazonTransactionType.TRANSFER.is_revenue()
        assert not AmazonTransactionType.ADJUSTMENT.is_revenue()

    def should_never_be_reverse_charge_eligible(self):
        """Amazon DE is domestic — no §13b Reverse Charge applies."""
        assert not AmazonTransactionType.ORDER.is_rc_eligible()
        assert not AmazonTransactionType.REFUND.is_rc_eligible()
        assert not AmazonTransactionType.TRANSFER.is_rc_eligible()
        assert not AmazonTransactionType.ADJUSTMENT.is_rc_eligible()

    def should_assign_order_to_8195_for_kleinunternehmer(self):
        account = AmazonTransactionType.ORDER.suggested_skr03_account(is_kleinunternehmer=True)
        assert account == 8195

    def should_assign_order_to_8400_for_regelbesteuert(self):
        account = AmazonTransactionType.ORDER.suggested_skr03_account(is_kleinunternehmer=False)
        assert account == 8400

    def should_assign_refund_to_8195_for_kleinunternehmer(self):
        account = AmazonTransactionType.REFUND.suggested_skr03_account(is_kleinunternehmer=True)
        assert account == 8195

    def should_assign_refund_to_8400_for_regelbesteuert(self):
        account = AmazonTransactionType.REFUND.suggested_skr03_account(is_kleinunternehmer=False)
        assert account == 8400

    def should_assign_transfer_to_1360_geldtransit(self):
        account = AmazonTransactionType.TRANSFER.suggested_skr03_account(is_kleinunternehmer=True)
        assert account == 1360

    def should_assign_adjustment_to_4900(self):
        account = AmazonTransactionType.ADJUSTMENT.suggested_skr03_account(is_kleinunternehmer=True)
        assert account == 4900

    def should_format_description_with_order_id(self):
        description = AmazonTransactionType.ORDER.format_description("306-9162999-5341943", None)
        assert description == "Amazon Verkauf #306-9162999-5341943"

    def should_format_description_without_order_id(self):
        description = AmazonTransactionType.ADJUSTMENT.format_description(None, "FBA Storage Fee")
        assert description == "Amazon Anpassung: FBA Storage Fee"


class TestAmazonAmountType:
    """Tests for AmazonAmountType enum."""

    def should_parse_known_amount_types(self):
        assert AmazonAmountType.from_string("ItemPrice") == AmazonAmountType.ITEM_PRICE
        assert AmazonAmountType.from_string("ItemFees") == AmazonAmountType.ITEM_FEES
        assert AmazonAmountType.from_string("Promotion") == AmazonAmountType.PROMOTION

    def should_handle_case_insensitive_parsing(self):
        assert AmazonAmountType.from_string("itemprice") == AmazonAmountType.ITEM_PRICE
        assert AmazonAmountType.from_string("ITEMFEES") == AmazonAmountType.ITEM_FEES

    def should_return_other_for_unknown_types(self):
        assert AmazonAmountType.from_string("UnknownType") == AmazonAmountType.OTHER
        assert AmazonAmountType.from_string("") == AmazonAmountType.OTHER


class TestSettlementSummaryDetection:
    """Tests for semantic Settlement Summary row detection."""

    def should_detect_settlement_summary_row(self):
        """Settlement summary has: empty transaction-type, filled total-amount, empty order-id."""
        row = {
            "transaction-type": "",
            "total-amount": "1234,56",
            "order-id": "",
        }
        assert is_settlement_summary_row(row)

    def should_not_detect_regular_order_as_summary(self):
        row = {
            "transaction-type": "Order",
            "total-amount": "",
            "order-id": "306-9162999-5341943",
        }
        assert not is_settlement_summary_row(row)

    def should_not_detect_row_with_order_id_as_summary(self):
        """Even if transaction-type is empty, having order-id disqualifies it."""
        row = {
            "transaction-type": "",
            "total-amount": "100,00",
            "order-id": "306-9162999-5341943",
        }
        assert not is_settlement_summary_row(row)


class TestNormalizeHeaders:
    """Tests for header normalization."""

    def should_normalize_headers_to_lowercase(self):
        headers = ["Settlement-ID", "Order-ID", "Amount-Type"]
        result = normalize_headers(headers)
        assert result == {"settlement-id": 0, "order-id": 1, "amount-type": 2}

    def should_strip_whitespace(self):
        headers = ["  settlement-id  ", "order-id "]
        result = normalize_headers(headers)
        assert "settlement-id" in result
        assert "order-id" in result


class TestAggregationKey:
    """Tests for row aggregation key generation."""

    def should_group_by_order_id_and_transaction_type(self):
        """Orders group by (order-id, transaction-type), NOT just order-id."""
        row = {
            "order-id": "306-9162999-5341943",
            "transaction-type": "Order",
        }
        key = AggregationKey.from_row(row)
        assert key.order_id == "306-9162999-5341943"
        assert key.transaction_type == "Order"

    def should_separate_order_and_refund_for_same_order_id(self):
        """Sale + Refund for same order-id must have DIFFERENT keys."""
        order_row = {"order-id": "306-9162999-5341943", "transaction-type": "Order"}
        refund_row = {"order-id": "306-9162999-5341943", "transaction-type": "Refund"}

        order_key = AggregationKey.from_row(order_row)
        refund_key = AggregationKey.from_row(refund_row)

        assert order_key != refund_key  # Critical: must NOT be equal
        assert order_key.order_id == refund_key.order_id  # Same order
        assert order_key.transaction_type != refund_key.transaction_type  # Different type

    def should_use_settlement_info_for_non_order_fees(self):
        """Non-order fees (no order-id) use settlement-id + posted-date + description."""
        row = {
            "order-id": "",
            "transaction-type": "",
            "settlement-id": "26579761962",
            "posted-date": "2024-01-15",
            "amount-description": "FBA Storage Fee",
        }
        key = AggregationKey.from_row(row)
        assert key.order_id is None
        assert key.settlement_id == "26579761962"
        assert key.posted_date == "2024-01-15"
        assert key.amount_description == "FBA Storage Fee"


class TestImportHash:
    """Tests for import hash computation."""

    def should_compute_deterministic_hash(self):
        hash1 = compute_amazon_import_hash(
            source_config_id="test-config",
            transaction_date=date(2024, 1, 10),
            amazon_type=AmazonTransactionType.ORDER,
            amount=Decimal("20.95"),
            order_id="306-9162999-5341943",
            row_type="sale",
        )
        hash2 = compute_amazon_import_hash(
            source_config_id="test-config",
            transaction_date=date(2024, 1, 10),
            amazon_type=AmazonTransactionType.ORDER,
            amount=Decimal("20.95"),
            order_id="306-9162999-5341943",
            row_type="sale",
        )
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def should_differentiate_sale_and_fee_for_same_order(self):
        """Sale row and Fee row for same order must have different hashes."""
        sale_hash = compute_amazon_import_hash(
            source_config_id="test-config",
            transaction_date=date(2024, 1, 10),
            amazon_type=AmazonTransactionType.ORDER,
            amount=Decimal("20.95"),
            order_id="306-9162999-5341943",
            row_type="sale",
        )
        fee_hash = compute_amazon_import_hash(
            source_config_id="test-config",
            transaction_date=date(2024, 1, 10),
            amazon_type=AmazonTransactionType.ORDER,
            amount=Decimal("-4.91"),
            order_id="306-9162999-5341943",
            row_type="fee",
        )
        assert sale_hash != fee_hash


# --- Parser Tests ---


class TestAmazonSettlementParser:
    """Tests for the main AmazonSettlementParser class."""

    def should_parse_simple_order_into_sale_and_fee_rows(self):
        """One order with ItemPrice + ItemFees → 2 output rows (Sale + Fee)."""
        csv_rows = [
            make_order_row("306-9162999-5341943", "ItemPrice", "Principal", "17,95"),
            make_order_row("306-9162999-5341943", "ItemPrice", "Shipping", "3,00"),
            make_order_row("306-9162999-5341943", "ItemFees", "Commission", "-3,20"),
            make_order_row("306-9162999-5341943", "ItemFees", "ShippingHB", "-0,53"),
        ]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser(is_kleinunternehmer=True)
        result = parser.parse(content, source_config_id="test-config")

        assert result.errors == []
        assert len(result.rows) == 2  # Sale + Fee

        # Find Sale row
        sale_rows = [r for r in result.rows if r.amount_type == AmazonAmountType.ITEM_PRICE]
        assert len(sale_rows) == 1
        sale = sale_rows[0]
        assert sale.amount == Decimal("20.95")  # 17.95 + 3.00
        assert sale.suggested_skr03 == 8195  # Kleinunternehmer
        assert sale.order_id == "306-9162999-5341943"

        # Find Fee row
        fee_rows = [r for r in result.rows if r.amount_type == AmazonAmountType.ITEM_FEES]
        assert len(fee_rows) == 1
        fee = fee_rows[0]
        assert fee.amount == Decimal("-3.73")  # -3.20 + -0.53
        assert fee.suggested_skr03 == 4761  # Amazon fees
        assert fee.order_id == "306-9162999-5341943"

    def should_handle_german_number_format(self):
        """German format: comma as decimal separator (17,95 = 17.95 EUR)."""
        csv_rows = [make_order_row("ORD-123", "ItemPrice", "Principal", "1.234,56")]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser()
        result = parser.parse(content, source_config_id="test-config")

        assert result.errors == []
        assert len(result.rows) == 1
        assert result.rows[0].amount == Decimal("1234.56")

    def should_keep_sale_and_refund_separate_for_same_order(self):
        """Sale + Refund for same order-id must be separate rows (NOT netted)."""
        csv_rows = [
            # Original sale
            make_order_row("306-9162999-5341943", "ItemPrice", "Principal", "20,00", "Order"),
            # Refund for same order
            make_order_row("306-9162999-5341943", "ItemPrice", "Principal", "-20,00", "Refund"),
        ]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser()
        result = parser.parse(content, source_config_id="test-config")

        assert result.errors == []
        # Must be 2 separate rows, NOT netted to 0
        assert len(result.rows) == 2

        order_rows = [r for r in result.rows if r.amazon_type == AmazonTransactionType.ORDER]
        refund_rows = [r for r in result.rows if r.amazon_type == AmazonTransactionType.REFUND]

        assert len(order_rows) == 1
        assert len(refund_rows) == 1
        assert order_rows[0].amount == Decimal("20.00")
        assert refund_rows[0].amount == Decimal("-20.00")

    def should_skip_settlement_summary_rows(self):
        """Settlement Summary rows should be skipped (metadata only)."""
        csv_rows = [make_order_row("ORD-123", "ItemPrice", "Principal", "10,00")]
        content = make_settlement_csv(csv_rows, include_summary=True)

        parser = AmazonSettlementParser()
        result = parser.parse(content, source_config_id="test-config")

        assert result.errors == []
        # Only the order row, not the summary
        assert len(result.rows) == 1
        assert result.skipped_rows == 1  # Summary was skipped

    def should_handle_promotions_reducing_sale_amount(self):
        """Promotion amounts (negative) should reduce the Sale row amount."""
        csv_rows = [
            make_order_row("ORD-123", "ItemPrice", "Principal", "25,00"),
            make_order_row("ORD-123", "Promotion", "Coupon", "-5,00"),
        ]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser()
        result = parser.parse(content, source_config_id="test-config")

        assert result.errors == []
        assert len(result.rows) == 1  # Only sale row (promotions merged)
        assert result.rows[0].amount == Decimal("20.00")  # 25 - 5

    def should_handle_non_order_fees_as_standalone_rows(self):
        """Fees without order-id (Storage, Subscriptions) → standalone Fee row."""
        csv_rows = [
            {
                "settlement-id": "26579761962",
                "settlement-start-date": "2024-01-01",
                "settlement-end-date": "2024-01-14",
                "deposit-date": "2024-01-16",
                "currency": "EUR",
                "transaction-type": "",  # No transaction type
                "order-id": "",  # No order
                "amount-type": "ItemFees",
                "amount-description": "FBA storage fee",
                "amount": "-39,99",
                "posted-date": "2024-01-15",
                "total-amount": "",  # Not a summary row
            },
        ]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser()
        result = parser.parse(content, source_config_id="test-config")

        assert result.errors == []
        assert len(result.rows) == 1
        fee = result.rows[0]
        assert fee.amount == Decimal("-39.99")
        assert fee.order_id is None
        assert fee.suggested_skr03 == 4761
        assert "FBA storage fee" in fee.description

    def should_reject_non_eur_currency(self):
        """Only EUR settlements are supported — USD should raise error."""
        csv_rows = [make_order_row("ORD-123", "ItemPrice", "Principal", "10.00", currency="USD")]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser()
        with pytest.raises(AmazonParseError) as exc_info:
            parser.parse(content, source_config_id="test-config")

        assert "Unsupported currency: USD" in str(exc_info.value)
        assert "Only EUR settlements are supported" in str(exc_info.value)

    def should_accept_eur_currency(self):
        """EUR settlements should parse without error."""
        csv_rows = [make_order_row("ORD-123", "ItemPrice", "Principal", "10,00", currency="EUR")]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser()
        result = parser.parse(content, source_config_id="test-config")

        assert result.errors == []
        assert len(result.rows) == 1

    def should_always_set_is_rc_eligible_to_false(self):
        """All Amazon rows must have is_rc_eligible=False (no Reverse Charge)."""
        csv_rows = [
            make_order_row("ORD-123", "ItemPrice", "Principal", "10,00"),
            make_order_row("ORD-123", "ItemFees", "Commission", "-1,50"),
        ]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser()
        result = parser.parse(content, source_config_id="test-config")

        for row in result.rows:
            assert row.is_rc_eligible is False

    def should_use_8400_for_regelbesteuert(self):
        """Regelbesteuert seller should get SKR03 8400 for sales."""
        csv_rows = [make_order_row("ORD-123", "ItemPrice", "Principal", "10,00")]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser(is_kleinunternehmer=False)
        result = parser.parse(content, source_config_id="test-config")

        assert result.rows[0].suggested_skr03 == 8400

    def should_handle_transfer_as_payout(self):
        """Transfer transaction type → Payout row with SKR03 1360 (Geldtransit)."""
        csv_rows = [
            {
                "settlement-id": "26579761962",
                "settlement-start-date": "2024-01-01",
                "settlement-end-date": "2024-01-14",
                "deposit-date": "2024-01-16",
                "currency": "EUR",
                "transaction-type": "Transfer",
                "order-id": "",
                "amount-type": "",
                "amount-description": "",
                "amount": "1234,56",
                "posted-date": "2024-01-16",
                "total-amount": "",
            },
        ]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser()
        result = parser.parse(content, source_config_id="test-config")

        assert len(result.rows) == 1
        payout = result.rows[0]
        assert payout.amazon_type == AmazonTransactionType.TRANSFER
        assert payout.amount == Decimal("1234.56")
        assert payout.suggested_skr03 == 1360  # Geldtransit
        assert payout.is_internal_transfer is True

    def should_extract_settlement_metadata(self):
        """Parser should extract settlement metadata from file."""
        csv_rows = [make_order_row("ORD-123", "ItemPrice", "Principal", "10,00")]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser()
        result = parser.parse(content, source_config_id="test-config")

        assert result.settlement_id == "26579761962"
        assert result.settlement_start == date(2024, 1, 1)
        assert result.settlement_end == date(2024, 1, 14)
        assert result.deposit_date == date(2024, 1, 16)


class TestEncodingDetection:
    """Tests for encoding and delimiter detection."""

    def should_handle_utf8_with_bom(self):
        """UTF-8 with BOM should be detected and parsed correctly."""
        csv_rows = [make_order_row("ORD-123", "ItemPrice", "Principal", "10,00")]
        content = make_settlement_csv(csv_rows)
        content_with_bom = b"\xef\xbb\xbf" + content

        parser = AmazonSettlementParser()
        result = parser.parse(content_with_bom, source_config_id="test-config")

        assert result.errors == []
        assert len(result.rows) == 1

    def should_handle_tab_delimiter(self):
        """Amazon Settlement files use tab delimiter."""
        csv_rows = [make_order_row("ORD-123", "ItemPrice", "Principal", "10,00")]
        content = make_settlement_csv(csv_rows, delimiter="\t")

        parser = AmazonSettlementParser()
        result = parser.parse(content, source_config_id="test-config")

        assert result.errors == []
        assert len(result.rows) == 1

    def should_reject_missing_required_columns(self):
        """File without required columns should raise error."""
        # Missing settlement-id and amount columns
        content = b"some-column\tother-column\nvalue1\tvalue2"

        parser = AmazonSettlementParser()
        with pytest.raises(AmazonParseError) as exc_info:
            parser.parse(content, source_config_id="test-config")

        assert "Missing required columns" in str(exc_info.value)

    def should_reject_empty_file(self):
        """Empty file should raise error."""
        parser = AmazonSettlementParser()
        with pytest.raises(AmazonParseError) as exc_info:
            parser.parse(b"", source_config_id="test-config")

        assert "Empty file" in str(exc_info.value)


class TestExtraDataFields:
    """Tests for extra_data field population."""

    def should_include_marketplace_metadata_in_extra_data(self):
        """extra_data should contain marketplace-specific metadata."""
        csv_rows = [make_order_row("ORD-123", "ItemPrice", "Principal", "10,00")]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser()
        result = parser.parse(content, source_config_id="test-config")

        assert len(result.rows) == 1
        extra = result.rows[0].extra_data

        assert extra.get("marketplace") == "amazon"
        assert extra.get("order_id") == "ORD-123"
        assert "marketplace_type" in extra
        assert "marketplace_category" in extra


class TestMultipleOrdersInOneSettlement:
    """Tests for files with multiple orders."""

    def should_aggregate_per_order_correctly(self):
        """Multiple orders in one file should create separate aggregation groups."""
        csv_rows = [
            # Order 1
            make_order_row("ORD-001", "ItemPrice", "Principal", "10,00"),
            make_order_row("ORD-001", "ItemFees", "Commission", "-1,50"),
            # Order 2
            make_order_row("ORD-002", "ItemPrice", "Principal", "20,00"),
            make_order_row("ORD-002", "ItemFees", "Commission", "-3,00"),
        ]
        content = make_settlement_csv(csv_rows)

        parser = AmazonSettlementParser()
        result = parser.parse(content, source_config_id="test-config")

        assert result.errors == []
        # 2 orders × 2 rows each = 4 output rows
        assert len(result.rows) == 4

        # Check Order 1
        order1_rows = [r for r in result.rows if r.order_id == "ORD-001"]
        assert len(order1_rows) == 2
        order1_sale = [r for r in order1_rows if r.amount > 0][0]
        assert order1_sale.amount == Decimal("10.00")

        # Check Order 2
        order2_rows = [r for r in result.rows if r.order_id == "ORD-002"]
        assert len(order2_rows) == 2
        order2_sale = [r for r in order2_rows if r.amount > 0][0]
        assert order2_sale.amount == Decimal("20.00")
