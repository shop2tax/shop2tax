"""Tests for Shopify Payment Transactions Parser.

Tests cover:
- All 6 transaction types detected correctly
- Fee extraction from column (not separate rows like Etsy)
- Timezone-aware date parsing
- 4-scenario SKR03 assignment
- Import hash deduplication
- Payout grouping
- §13b Reverse Charge on fees
"""

from datetime import date
from decimal import Decimal

import pytest
from app.services.shopify_parser import (
    ShopifyParseError,
    ShopifyStatementParser,
    ShopifyTransactionType,
    compute_shopify_import_hash,
    detect_type,
    extract_order_id,
    normalize_headers,
    parse_shopify_datetime,
)


class TestShopifyTransactionType:
    """Tests for ShopifyTransactionType enum and helper methods."""

    def should_identify_revenue_types(self):
        assert ShopifyTransactionType.CHARGE.is_revenue()
        assert ShopifyTransactionType.REFUND.is_revenue()
        assert not ShopifyTransactionType.CHARGEBACK.is_revenue()
        assert not ShopifyTransactionType.PAYOUT.is_revenue()
        assert not ShopifyTransactionType.ADJUSTMENT.is_revenue()
        assert not ShopifyTransactionType.RESERVE.is_revenue()

    def should_identify_reverse_charge_eligible_types(self):
        # charge, refund, chargeback fees are RC-eligible (Shopify = Irish MoR)
        assert ShopifyTransactionType.CHARGE.is_rc_eligible()
        assert ShopifyTransactionType.REFUND.is_rc_eligible()
        assert ShopifyTransactionType.CHARGEBACK.is_rc_eligible()
        # payout, adjustment, reserve fees are NOT RC-eligible
        assert not ShopifyTransactionType.PAYOUT.is_rc_eligible()
        assert not ShopifyTransactionType.ADJUSTMENT.is_rc_eligible()
        assert not ShopifyTransactionType.RESERVE.is_rc_eligible()

    def should_format_charge_description_with_card_brand(self):
        description = ShopifyTransactionType.CHARGE.format_description("3703", "Mastercard")
        assert description == "Shopify Verkauf #3703 (Mastercard)"

    def should_format_charge_description_without_card_brand(self):
        description = ShopifyTransactionType.CHARGE.format_description("3703", None)
        assert description == "Shopify Verkauf #3703"

    def should_format_refund_description(self):
        description = ShopifyTransactionType.REFUND.format_description("3703", "Visa")
        assert description == "Shopify Rückerstattung #3703"  # Card brand not shown for refunds

    def should_format_payout_description(self):
        description = ShopifyTransactionType.PAYOUT.format_description(None, None)
        assert description == "Shopify Auszahlung"


class TestShopifySKR03Assignment:
    """Tests for 4-scenario SKR03 account assignment."""

    # === Transaction Amount SKR03 ===

    def should_assign_charge_to_8195_for_kleinunternehmer(self):
        """Scenario B: Kleinunternehmer + USt-ID → Sales on 8195."""
        account = ShopifyTransactionType.CHARGE.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=True,
        )
        assert account == 8195

    def should_assign_charge_to_8400_for_regelbesteuert(self):
        """Scenario A: Regelbesteuert + USt-ID → Sales on 8400."""
        account = ShopifyTransactionType.CHARGE.suggested_skr03_account(
            is_kleinunternehmer=False,
            has_ust_id=True,
        )
        assert account == 8400

    def should_assign_charge_to_8195_for_kleinunternehmer_without_ust_id(self):
        """Scenario D: Kleinunternehmer + no USt-ID → Sales still on 8195."""
        account = ShopifyTransactionType.CHARGE.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=False,
        )
        assert account == 8195

    def should_assign_charge_to_8400_for_regelbesteuert_without_ust_id(self):
        """Scenario C: Regelbesteuert + no USt-ID → Sales still on 8400."""
        account = ShopifyTransactionType.CHARGE.suggested_skr03_account(
            is_kleinunternehmer=False,
            has_ust_id=False,
        )
        assert account == 8400

    def should_assign_refund_same_as_charge(self):
        """Refund reduces revenue → same account as charge (Erlösminderung)."""
        account = ShopifyTransactionType.REFUND.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=True,
        )
        assert account == 8195

    def should_assign_chargeback_same_as_charge(self):
        """Chargeback reduces revenue → same account as charge."""
        account = ShopifyTransactionType.CHARGEBACK.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=True,
        )
        assert account == 8195

    def should_assign_payout_to_1360(self):
        """Payout → Geldtransit 1360."""
        account = ShopifyTransactionType.PAYOUT.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=True,
        )
        assert account == 1360

    def should_assign_adjustment_to_4900(self):
        """Adjustment → Sonstige betriebliche Aufwendungen 4900."""
        account = ShopifyTransactionType.ADJUSTMENT.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=True,
        )
        assert account == 4900

    def should_assign_reserve_to_4900(self):
        """Reserve → Sonstige betriebliche Aufwendungen 4900."""
        account = ShopifyTransactionType.RESERVE.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=True,
        )
        assert account == 4900

    # === Fee SKR03 ===

    def should_assign_fee_to_3165_for_scenario_b(self):
        """Scenario B: Kleinunternehmer + USt-ID → §13b ohne VSt (3165)."""
        account = ShopifyTransactionType.CHARGE.suggested_fee_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=True,
        )
        assert account == 3165

    def should_assign_fee_to_3125_for_scenario_a(self):
        """Scenario A: Regelbesteuert + USt-ID → §13b mit VSt (3125)."""
        account = ShopifyTransactionType.CHARGE.suggested_fee_skr03_account(
            is_kleinunternehmer=False,
            has_ust_id=True,
        )
        assert account == 3125

    def should_assign_fee_to_4763_without_ust_id(self):
        """Scenarios C/D: No USt-ID → brutto fees on 4763 (Shopify Gebühren)."""
        # Scenario C
        account_c = ShopifyTransactionType.CHARGE.suggested_fee_skr03_account(
            is_kleinunternehmer=False,
            has_ust_id=False,
        )
        assert account_c == 4763

        # Scenario D
        account_d = ShopifyTransactionType.CHARGE.suggested_fee_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=False,
        )
        assert account_d == 4763


class TestShopifyTypeDetection:
    """Tests for detect_type() function."""

    def should_detect_charge(self):
        assert detect_type("charge") == ShopifyTransactionType.CHARGE
        assert detect_type("Charge") == ShopifyTransactionType.CHARGE
        assert detect_type("CHARGE") == ShopifyTransactionType.CHARGE

    def should_detect_refund(self):
        assert detect_type("refund") == ShopifyTransactionType.REFUND
        assert detect_type("Refund") == ShopifyTransactionType.REFUND

    def should_detect_chargeback(self):
        assert detect_type("chargeback") == ShopifyTransactionType.CHARGEBACK

    def should_detect_adjustment(self):
        assert detect_type("adjustment") == ShopifyTransactionType.ADJUSTMENT

    def should_detect_payout(self):
        assert detect_type("payout") == ShopifyTransactionType.PAYOUT

    def should_detect_reserve(self):
        assert detect_type("reserve") == ShopifyTransactionType.RESERVE

    def should_reject_invalid_type(self):
        with pytest.raises(ValueError):
            detect_type("invalid_type")

        with pytest.raises(ValueError):
            detect_type("sale")  # Shopify uses "charge", not "sale"


class TestShopifyOrderIdExtraction:
    """Tests for extract_order_id() function."""

    def should_extract_order_number_with_hash(self):
        assert extract_order_id("#3703") == "3703"
        assert extract_order_id("#123456") == "123456"

    def should_extract_order_number_without_hash(self):
        assert extract_order_id("3703") == "3703"
        assert extract_order_id("123456") == "123456"

    def should_return_none_for_empty_string(self):
        assert extract_order_id("") is None
        assert extract_order_id("   ") is None

    def should_return_none_for_non_numeric(self):
        assert extract_order_id("ABC") is None
        assert extract_order_id("#ABC") is None


class TestShopifyDateParsing:
    """Tests for parse_shopify_datetime() function."""

    def should_parse_timezone_aware_datetime(self):
        """Shopify format: 2026-01-19 12:07:45 +0100"""
        result = parse_shopify_datetime("2026-01-19 12:07:45 +0100")
        assert result == date(2026, 1, 19)

    def should_parse_different_timezone_offsets(self):
        result = parse_shopify_datetime("2026-06-15 08:30:00 +0200")
        assert result == date(2026, 6, 15)

        result = parse_shopify_datetime("2026-12-01 23:59:59 -0500")
        assert result == date(2026, 12, 1)

    def should_parse_iso_date_only(self):
        result = parse_shopify_datetime("2026-01-19")
        assert result == date(2026, 1, 19)

    def should_reject_empty_string(self):
        with pytest.raises(ValueError):
            parse_shopify_datetime("")

        with pytest.raises(ValueError):
            parse_shopify_datetime("   ")


class TestShopifyHeaderNormalization:
    """Tests for normalize_headers() function."""

    def should_normalize_standard_headers(self):
        headers = [
            "Transaction Date",
            "Type",
            "Order",
            "Card Brand",
            "Card Source",
            "Payout Status",
            "Payout Date",
            "Payout ID",
            "Available On",
            "Amount",
            "Fee",
            "Net",
            "Checkout",
            "Payment Method Name",
            "Presentment Amount",
            "Presentment Currency",
            "Currency",
            "VAT",
        ]
        result = normalize_headers(headers)

        assert result["transaction date"] == 0
        assert result["type"] == 1
        assert result["order"] == 2
        assert result["amount"] == 9
        assert result["fee"] == 10
        assert result["net"] == 11
        assert result["vat"] == 17


class TestShopifyImportHash:
    """Tests for compute_shopify_import_hash() function."""

    def should_compute_deterministic_hash(self):
        hash1 = compute_shopify_import_hash(
            source_config_id="abc-123",
            transaction_date=date(2026, 1, 19),
            shopify_type=ShopifyTransactionType.CHARGE,
            amount=Decimal("37.90"),
            order_id="3703",
            checkout_id="#51257260474634",
        )
        hash2 = compute_shopify_import_hash(
            source_config_id="abc-123",
            transaction_date=date(2026, 1, 19),
            shopify_type=ShopifyTransactionType.CHARGE,
            amount=Decimal("37.90"),
            order_id="3703",
            checkout_id="#51257260474634",
        )
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def should_differ_by_source(self):
        hash1 = compute_shopify_import_hash("source-1", date(2026, 1, 19), ShopifyTransactionType.CHARGE, Decimal("100"), "123", "checkout")
        hash2 = compute_shopify_import_hash("source-2", date(2026, 1, 19), ShopifyTransactionType.CHARGE, Decimal("100"), "123", "checkout")
        assert hash1 != hash2

    def should_differ_by_type(self):
        hash1 = compute_shopify_import_hash("source-1", date(2026, 1, 19), ShopifyTransactionType.CHARGE, Decimal("100"), "123", "checkout")
        hash2 = compute_shopify_import_hash("source-1", date(2026, 1, 19), ShopifyTransactionType.REFUND, Decimal("100"), "123", "checkout")
        assert hash1 != hash2

    def should_differ_by_checkout_id(self):
        """Checkout ID is unique per transaction — differentiates same order/date rows."""
        hash1 = compute_shopify_import_hash("source-1", date(2026, 1, 19), ShopifyTransactionType.CHARGE, Decimal("100"), "123", "checkout-1")
        hash2 = compute_shopify_import_hash("source-1", date(2026, 1, 19), ShopifyTransactionType.CHARGE, Decimal("100"), "123", "checkout-2")
        assert hash1 != hash2


class TestShopifyFeeHandling:
    """Tests for Shopify fee extraction — synthetic fee rows from Fee column."""

    def should_generate_synthetic_fee_row_from_column(self):
        """Shopify fees are per-row in the Fee column → generates separate fee transaction."""
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        # 1 charge + 1 synthetic fee = 2 rows
        assert len(result.rows) == 2
        charge = result.rows[0]
        assert charge.amount == Decimal("37.90")
        assert charge.fee == Decimal("1.10")
        assert charge.net == Decimal("36.80")

        fee_row = result.rows[1]
        assert fee_row.amount == Decimal("-1.10")
        assert fee_row.counterparty == "Shopify International Ltd"
        assert fee_row.description == "Shopify Gebühr #3703"
        assert fee_row.source_reference == "Order #3703_FEE"
        assert fee_row.suggested_skr03 == 3165  # KU + USt-ID → §13b ohne VSt
        assert fee_row.extra_data["marketplace_type"] == "fee"
        assert fee_row.extra_data["marketplace_category"] == "fee"

    def should_handle_zero_fee(self):
        """Some rows (like payout) have zero fee → no synthetic fee row."""
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-02-02 00:00:00 +0100,payout,,,,paid,2026-02-02,140769394954,2026-02-02,-36.80,0.00,-36.80,,,36.80,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 1  # No synthetic fee row for payout
        payout = result.rows[0]
        assert payout.fee == Decimal("0")
        assert payout.is_rc_eligible is False

    def should_generate_fee_rows_for_multiple_charges(self):
        """Each charge with fee generates a synthetic fee row."""
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
2026-01-20 15:30:00 +0100,charge,#3704,visa,online,paid,2026-02-02,140769394954,2026-01-23,52.00,1.64,50.36,#51257260474635,card,52.00,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        # 2 charges + 2 fees = 4 rows
        assert len(result.rows) == 4
        fee_rows = [r for r in result.rows if r.extra_data.get("marketplace_type") == "fee"]
        assert len(fee_rows) == 2
        total_fee_amounts = sum(abs(r.amount) for r in fee_rows)
        assert total_fee_amounts == Decimal("2.74")  # 1.10 + 1.64


class TestShopifyStatementParser:
    """Integration tests for ShopifyStatementParser class."""

    def should_parse_minimal_csv(self):
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 2  # charge + synthetic fee
        assert len(result.errors) == 0

        charge = result.rows[0]
        assert charge.shopify_type == ShopifyTransactionType.CHARGE
        assert charge.amount == Decimal("37.90")
        assert charge.fee == Decimal("1.10")
        assert charge.net == Decimal("36.80")
        assert charge.date == date(2026, 1, 19)
        assert charge.order_id == "3703"
        assert charge.card_brand == "master"
        assert charge.payout_id == "140769394954"
        assert charge.suggested_skr03 == 8195  # Kleinunternehmer

    def should_parse_mixed_types(self):
        """Parse CSV with charge, refund, and payout."""
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
2026-01-20 10:00:00 +0100,refund,#3703,master,online,paid,2026-02-02,140769394954,2026-01-23,-37.90,-1.10,-36.80,#51257260474634,card,-37.90,EUR,EUR,0.00
2026-02-02 00:00:00 +0100,payout,,,,paid,2026-02-02,140769394954,2026-02-02,-36.80,0.00,-36.80,,,36.80,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        # charge + fee, refund + fee, payout = 5 rows
        assert len(result.rows) == 5
        non_fee_rows = [r for r in result.rows if r.extra_data.get("marketplace_type") != "fee"]
        assert len(non_fee_rows) == 3
        assert non_fee_rows[0].shopify_type == ShopifyTransactionType.CHARGE
        assert non_fee_rows[1].shopify_type == ShopifyTransactionType.REFUND
        assert non_fee_rows[2].shopify_type == ShopifyTransactionType.PAYOUT

    def should_mark_payout_as_internal_transfer(self):
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-02-02 00:00:00 +0100,payout,,,,paid,2026-02-02,140769394954,2026-02-02,-36.80,0.00,-36.80,,,36.80,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 1
        payout = result.rows[0]
        assert payout.is_internal_transfer is True
        assert payout.suggested_skr03 == 1360
        assert payout.counterparty == "Shopify Auszahlung"

    def should_set_extra_data_for_marketplace(self):
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        charge = result.rows[0]
        assert charge.extra_data["marketplace"] == "shopify"
        assert charge.extra_data["marketplace_type"] == "charge"
        assert charge.extra_data["marketplace_category"] == "revenue"
        assert charge.extra_data["order_id"] == "3703"
        assert charge.extra_data["card_brand"] == "master"
        assert charge.extra_data["payout_id"] == "140769394954"
        assert charge.extra_data["fee"] == "1.10"

        fee_row = result.rows[1]
        assert fee_row.extra_data["marketplace"] == "shopify"
        assert fee_row.extra_data["marketplace_type"] == "fee"
        assert fee_row.extra_data["marketplace_category"] == "fee"
        assert fee_row.extra_data["order_id"] == "3703"

    def should_use_regelbesteuert_accounts_when_configured(self):
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser(is_kleinunternehmer=False, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert result.rows[0].suggested_skr03 == 8400  # Regelbesteuert Erlöse

    def should_handle_semicolon_delimiter(self):
        csv_content = b"""Transaction Date;Type;Order;Card Brand;Card Source;Payout Status;Payout Date;Payout ID;Available On;Amount;Fee;Net;Checkout;Payment Method Name;Presentment Amount;Presentment Currency;Currency;VAT
2026-01-19 12:07:45 +0100;charge;#3703;master;online;paid;2026-02-02;140769394954;2026-01-22;37.90;1.10;36.80;#51257260474634;card;37.90;EUR;EUR;0.00
"""
        parser = ShopifyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 2  # charge + fee
        assert result.rows[0].amount == Decimal("37.90")

    def should_reject_csv_without_required_columns(self):
        csv_content = b"""Name,Value
Test,123
"""
        parser = ShopifyStatementParser()
        with pytest.raises(ShopifyParseError) as exc_info:
            parser.parse(csv_content, "test-source-id")

        assert "Missing required columns" in str(exc_info.value)

    def should_handle_malformed_rows_gracefully(self):
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
invalid date,charge,#3704,visa,online,paid,2026-02-02,140769394954,2026-01-23,52.00,1.64,50.36,#51257260474635,card,52.00,EUR,EUR,0.00
2026-01-21 09:00:00 +0100,charge,#3705,amex,online,paid,2026-02-02,140769394954,2026-01-24,25.00,0.75,24.25,#51257260474636,card,25.00,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        # 2 valid charges + 2 synthetic fees = 4, plus 1 error
        assert len(result.rows) == 4
        assert len(result.errors) == 1
        assert "Row 3" in result.errors[0]

    def should_build_source_reference_for_charge(self):
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert result.rows[0].source_reference == "Order #3703"

    def should_build_source_reference_for_refund(self):
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-20 10:00:00 +0100,refund,#3703,master,online,paid,2026-02-02,140769394954,2026-01-23,-37.90,-1.10,-36.80,#51257260474634,card,-37.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert result.rows[0].source_reference == "Order #3703_REFUND"

    def should_build_source_reference_for_payout(self):
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-02-02 00:00:00 +0100,payout,,,,paid,2026-02-02,140769394954,2026-02-02,-36.80,0.00,-36.80,,,36.80,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert result.rows[0].source_reference == "Payout_2026-02-02"

    def should_parse_chargeback(self):
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-25 14:00:00 +0100,chargeback,#3703,master,online,paid,2026-02-05,140769394955,2026-01-28,-37.90,15.00,-52.90,#51257260474634,card,-37.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 2  # chargeback + fee
        chargeback = result.rows[0]
        assert chargeback.shopify_type == ShopifyTransactionType.CHARGEBACK
        assert chargeback.amount == Decimal("-37.90")
        assert chargeback.fee == Decimal("15.00")  # Chargeback fee
        assert chargeback.source_reference == "Order #3703_CHARGEBACK"

        fee_row = result.rows[1]
        assert fee_row.amount == Decimal("-15.00")
        assert fee_row.source_reference == "Order #3703_FEE"

    def should_set_correct_counterparty(self):
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
2026-01-20 10:00:00 +0100,refund,#3703,master,online,paid,2026-02-02,140769394954,2026-01-23,-37.90,-1.10,-36.80,#51257260474634,card,-37.90,EUR,EUR,0.00
2026-02-02 00:00:00 +0100,payout,,,,paid,2026-02-02,140769394954,2026-02-02,-36.80,0.00,-36.80,,,36.80,EUR,EUR,0.00
2026-01-25 14:00:00 +0100,adjustment,#3703,,,paid,2026-02-05,140769394955,2026-01-28,-5.00,0.00,-5.00,,,,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        # Filter to non-fee rows for counterparty assertions
        non_fee = [r for r in result.rows if r.extra_data.get("marketplace_type") != "fee"]
        assert non_fee[0].counterparty == "Shopify Kunde"  # Charge
        assert non_fee[1].counterparty == "Shopify Kunde"  # Refund
        assert non_fee[2].counterparty == "Shopify Auszahlung"  # Payout
        assert non_fee[3].counterparty == "Shopify International Ltd"  # Adjustment

        # Fee rows always have Shopify International Ltd
        fee_rows = [r for r in result.rows if r.extra_data.get("marketplace_type") == "fee"]
        for fee_row in fee_rows:
            assert fee_row.counterparty == "Shopify International Ltd"


class TestShopifyReverseChargeCalculation:
    """Tests for §13b Reverse Charge calculation on Shopify fees.

    Key difference from Etsy: Shopify fees are per-row (Fee column),
    not separate rows. RC is calculated from the Fee column value.
    """

    def should_set_rc_fee_amount_on_synthetic_fee_row(self):
        """RC lives on the synthetic fee row, not on the charge row."""
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 2
        charge = result.rows[0]
        assert charge.is_rc_eligible is False  # Sale is not RC
        assert charge.rc_fee_amount == Decimal("0")

        fee_row = result.rows[1]
        assert fee_row.is_rc_eligible is True
        assert fee_row.rc_fee_amount == Decimal("1.10")

    def should_not_set_rc_for_payout(self):
        """Payout rows should have rc_fee_amount = 0 (payouts are NOT RC-eligible)."""
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-02-02 00:00:00 +0100,payout,,,,paid,2026-02-02,140769394954,2026-02-02,-36.80,0.00,-36.80,,,36.80,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 1
        payout = result.rows[0]
        assert payout.is_rc_eligible is False
        assert payout.rc_fee_amount == Decimal("0")

    def should_not_set_rc_without_ust_id(self):
        """Without USt-ID, fee row still generated but not RC-eligible."""
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser(is_kleinunternehmer=True, has_ust_id=False)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 2  # charge + fee (fee still tracked as expense)
        fee_row = result.rows[1]
        assert fee_row.is_rc_eligible is False
        assert fee_row.rc_fee_amount == Decimal("0")
        assert fee_row.suggested_skr03 == 4763  # brutto, no RC

    def should_calculate_correct_rc_base_for_multiple_charges(self):
        """RC base = sum of rc_fee_amount from synthetic fee rows."""
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
2026-01-20 15:30:00 +0100,charge,#3704,visa,online,paid,2026-02-02,140769394954,2026-01-23,52.00,1.64,50.36,#51257260474635,card,52.00,EUR,EUR,0.00
2026-02-02 00:00:00 +0100,payout,,,,paid,2026-02-02,140769394954,2026-02-02,-89.90,0.00,-89.90,,,89.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        # 2 charges + 2 fees + 1 payout = 5 rows
        assert len(result.rows) == 5

        # RC base = sum of rc_fee_amount from fee rows
        rc_fee_sum = sum(row.rc_fee_amount for row in result.rows)
        assert rc_fee_sum == Decimal("2.74")  # 1.10 + 1.64 (only on fee rows)

        # Verify fee row amounts match invoice total
        fee_rows = [r for r in result.rows if r.extra_data.get("marketplace_type") == "fee"]
        total_fee_amounts = sum(abs(r.amount) for r in fee_rows)
        assert total_fee_amounts == Decimal("2.74")

    def should_set_rc_for_chargeback_fees(self):
        """Chargeback fee row is RC-eligible (Shopify = Irish MoR)."""
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-25 14:00:00 +0100,chargeback,#3703,master,online,paid,2026-02-05,140769394955,2026-01-28,-37.90,15.00,-52.90,#51257260474634,card,-37.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 2
        fee_row = result.rows[1]
        assert fee_row.is_rc_eligible is True
        assert fee_row.rc_fee_amount == Decimal("15.00")

    def should_set_rc_for_refund_fees(self):
        """Refund fee row (negative = credit back) is RC-eligible."""
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-20 10:00:00 +0100,refund,#3703,master,online,paid,2026-02-02,140769394954,2026-01-23,-37.90,-1.10,-36.80,#51257260474634,card,-37.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 2
        fee_row = result.rows[1]
        assert fee_row.is_rc_eligible is True
        assert fee_row.rc_fee_amount == Decimal("1.10")  # abs(-1.10)


class TestShopifyPayoutGrouping:
    """Tests for Payout ID grouping (multiple charges → 1 payout)."""

    def should_share_payout_id_across_charges(self):
        """Multiple charges in same payout period share Payout ID."""
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
2026-01-20 15:30:00 +0100,charge,#3704,visa,online,paid,2026-02-02,140769394954,2026-01-23,52.00,1.64,50.36,#51257260474635,card,52.00,EUR,EUR,0.00
2026-02-02 00:00:00 +0100,payout,,,,paid,2026-02-02,140769394954,2026-02-02,-89.90,0.00,-89.90,,,89.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        # 2 charges + 2 fees + 1 payout = 5
        assert len(result.rows) == 5

        # All rows share same payout_id
        payout_ids = {row.payout_id for row in result.rows}
        assert payout_ids == {"140769394954"}

        # Verify amounts on charge rows
        charges = [r for r in result.rows if r.extra_data.get("marketplace_type") == "charge"]
        payout = [r for r in result.rows if r.shopify_type == ShopifyTransactionType.PAYOUT][0]

        total_net = sum(c.net for c in charges)
        assert total_net == Decimal("87.16")  # 36.80 + 50.36
        assert payout.amount == Decimal("-89.90")

    def should_store_payout_date(self):
        """Payout date should be extracted from Payout Date column."""
        csv_content = b"""Transaction Date,Type,Order,Card Brand,Card Source,Payout Status,Payout Date,Payout ID,Available On,Amount,Fee,Net,Checkout,Payment Method Name,Presentment Amount,Presentment Currency,Currency,VAT
2026-01-19 12:07:45 +0100,charge,#3703,master,online,paid,2026-02-02,140769394954,2026-01-22,37.90,1.10,36.80,#51257260474634,card,37.90,EUR,EUR,0.00
"""
        parser = ShopifyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert result.rows[0].payout_date == date(2026, 2, 2)
