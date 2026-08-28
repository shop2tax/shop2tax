"""Tests for Etsy Statement Parser.

Tests cover:
- All 13 transaction types detected correctly
- Amount parsing (German/English formats, currency symbols, negatives)
- Date parsing (German + English month names, various formats)
- CSV robustness (encoding detection, delimiter sniffing, inline headers)
- 4-scenario SKR03 assignment
- Import hash deduplication
"""

from datetime import date
from decimal import Decimal

import pytest
from app.services.csv_utils import parse_localized_date, parse_money, sniff_delimiter, sniff_encoding
from app.services.etsy_parser import (
    COL_AMOUNT,
    COL_DATE,
    COL_INFO,
    COL_NET,
    COL_TITLE,
    COL_TYPE,
    EtsyParseError,
    EtsyStatementParser,
    EtsyTransactionType,
    compute_etsy_import_hash,
    detect_type,
    extract_order_id,
    normalize_headers,
)


class TestEtsyTransactionType:
    """Tests for EtsyTransactionType enum and helper methods."""

    def should_identify_fee_types(self):
        assert EtsyTransactionType.FEE_TRANSACTION_SHIPPING.is_fee()
        assert EtsyTransactionType.FEE_TRANSACTION_ITEM.is_fee()
        assert EtsyTransactionType.FEE_PROCESSING.is_fee()
        assert EtsyTransactionType.FEE_LISTING.is_fee()
        assert not EtsyTransactionType.SALE.is_fee()
        assert not EtsyTransactionType.CREDIT_TRANSACTION.is_fee()

    def should_identify_credit_types(self):
        assert EtsyTransactionType.CREDIT_TRANSACTION.is_credit()
        assert EtsyTransactionType.CREDIT_PROCESSING.is_credit()
        assert EtsyTransactionType.CREDIT_LISTING.is_credit()
        assert not EtsyTransactionType.FEE_PROCESSING.is_credit()

    def should_identify_marketing_types(self):
        assert EtsyTransactionType.MARKETING_ADS.is_marketing()
        assert EtsyTransactionType.MARKETING_OFFSITE.is_marketing()
        assert not EtsyTransactionType.FEE_PROCESSING.is_marketing()

    def should_identify_reverse_charge_eligible_types(self):
        # Fees, credits, and marketing are RC-eligible
        assert EtsyTransactionType.FEE_PROCESSING.is_rc_eligible()
        assert EtsyTransactionType.CREDIT_TRANSACTION.is_rc_eligible()
        assert EtsyTransactionType.MARKETING_ADS.is_rc_eligible()
        # Sales, refunds, payouts are NOT RC-eligible
        assert not EtsyTransactionType.SALE.is_rc_eligible()
        assert not EtsyTransactionType.REFUND.is_rc_eligible()
        assert not EtsyTransactionType.PAYOUT.is_rc_eligible()
        assert not EtsyTransactionType.SALES_TAX.is_rc_eligible()


class TestSKR03Assignment:
    """Tests for 4-scenario SKR03 account assignment."""

    def should_assign_sale_to_8195_for_kleinunternehmer(self):
        account = EtsyTransactionType.SALE.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=True,
        )
        assert account == 8195

    def should_assign_sale_to_8400_for_regelbesteuert(self):
        account = EtsyTransactionType.SALE.suggested_skr03_account(
            is_kleinunternehmer=False,
            has_ust_id=True,
        )
        assert account == 8400

    def should_assign_sale_to_8195_for_kleinunternehmer_without_ust_id(self):
        """Scenario D: Kleinunternehmer + no USt-ID → SALE still on 8195."""
        account = EtsyTransactionType.SALE.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=False,
        )
        assert account == 8195

    def should_assign_sale_to_8400_for_regelbesteuert_without_ust_id(self):
        """Scenario C: Regelbesteuert + no USt-ID → SALE still on 8400."""
        account = EtsyTransactionType.SALE.suggested_skr03_account(
            is_kleinunternehmer=False,
            has_ust_id=False,
        )
        assert account == 8400

    def should_assign_fee_to_3165_for_scenario_b(self):
        """Scenario B: Kleinunternehmer + USt-ID → §13b ohne VSt."""
        account = EtsyTransactionType.FEE_PROCESSING.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=True,
        )
        assert account == 3165

    def should_assign_fee_to_3125_for_scenario_a(self):
        """Scenario A: Regelbesteuert + USt-ID → §13b mit VSt."""
        account = EtsyTransactionType.FEE_PROCESSING.suggested_skr03_account(
            is_kleinunternehmer=False,
            has_ust_id=True,
        )
        assert account == 3125

    def should_assign_fee_to_4761_for_scenario_c_d(self):
        """Scenarios C/D: No USt-ID → brutto fees on 4761."""
        # Scenario C
        account_c = EtsyTransactionType.FEE_PROCESSING.suggested_skr03_account(
            is_kleinunternehmer=False,
            has_ust_id=False,
        )
        assert account_c == 4761

        # Scenario D
        account_d = EtsyTransactionType.FEE_PROCESSING.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=False,
        )
        assert account_d == 4761

    def should_assign_marketing_to_rc_accounts_when_ust_id_registered(self):
        """Marketing fees also get RC treatment."""
        account = EtsyTransactionType.MARKETING_ADS.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=True,
        )
        assert account == 3165

    def should_assign_sales_tax_to_1590(self):
        """Sales tax is durchlaufender Posten → 1590."""
        account = EtsyTransactionType.SALES_TAX.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=True,
        )
        assert account == 1590

    def should_assign_payout_to_1360(self):
        """Payout → Geldtransit 1360."""
        account = EtsyTransactionType.PAYOUT.suggested_skr03_account(
            is_kleinunternehmer=True,
            has_ust_id=True,
        )
        assert account == 1360


class TestTypeDetection:
    """Tests for detect_type() function."""

    def should_detect_sale(self):
        assert detect_type("Sale", "Payment for Order #123") == EtsyTransactionType.SALE
        assert detect_type("Verkauf", "Zahlung für Bestellung") == EtsyTransactionType.SALE

    def should_detect_refund(self):
        assert detect_type("Refund", "Refund for Order #123") == EtsyTransactionType.REFUND
        assert detect_type("Rückerstattung", "Erstattung") == EtsyTransactionType.REFUND

    def should_detect_sales_tax(self):
        assert detect_type("Tax", "Sales tax paid by buyer") == EtsyTransactionType.SALES_TAX

    def should_detect_payout(self):
        assert detect_type("Überweisung", "€195.32 an dein Bankkonto überwiesen") == EtsyTransactionType.PAYOUT
        assert detect_type("Payout", "Transfer to bank") == EtsyTransactionType.PAYOUT

    def should_detect_transaction_fee_shipping(self):
        assert detect_type("Fee", "Transaction fee: Shipping") == EtsyTransactionType.FEE_TRANSACTION_SHIPPING
        assert detect_type("Gebühr", "Transaktionsgebühr: Versand") == EtsyTransactionType.FEE_TRANSACTION_SHIPPING

    def should_detect_transaction_fee_item(self):
        assert detect_type("Fee", "Transaction fee: Handmade Widget") == EtsyTransactionType.FEE_TRANSACTION_ITEM
        assert detect_type("Gebühr", "Transaktionsgebühr: Artikel") == EtsyTransactionType.FEE_TRANSACTION_ITEM

    def should_detect_processing_fee(self):
        assert detect_type("Fee", "Processing fee") == EtsyTransactionType.FEE_PROCESSING
        assert detect_type("Gebühr", "Zahlungsabwicklung") == EtsyTransactionType.FEE_PROCESSING

    def should_detect_listing_fee(self):
        assert detect_type("Fee", "Einstellgebühr (0,20 USD)") == EtsyTransactionType.FEE_LISTING
        assert detect_type("Fee", "Listing fee ($0.20)") == EtsyTransactionType.FEE_LISTING

    def should_detect_credit_transaction(self):
        assert detect_type("Fee", "Credit for transaction fee") == EtsyTransactionType.CREDIT_TRANSACTION

    def should_detect_credit_processing(self):
        assert detect_type("Fee", "Credit for processing fee") == EtsyTransactionType.CREDIT_PROCESSING

    def should_detect_credit_listing(self):
        assert detect_type("Fee", "Credit for listing fee") == EtsyTransactionType.CREDIT_LISTING
        assert detect_type("Fee", "Gutschrift für Einstellgebühr") == EtsyTransactionType.CREDIT_LISTING

    def should_detect_etsy_ads(self):
        assert detect_type("Marketing", "Etsy Ads") == EtsyTransactionType.MARKETING_ADS
        assert detect_type("Fee", "Etsy Ads campaign") == EtsyTransactionType.MARKETING_ADS

    def should_detect_offsite_ads(self):
        assert detect_type("Marketing", "Offsite Ads") == EtsyTransactionType.MARKETING_OFFSITE
        assert detect_type("Fee", "Gebühr für Verkauf über Offsite Ads") == EtsyTransactionType.MARKETING_OFFSITE


class TestAmountParsing:
    """Tests for parse_money() function."""

    def should_parse_german_format(self):
        assert parse_money("1.234,56") == Decimal("1234.56")
        assert parse_money("-1.234,56") == Decimal("-1234.56")
        assert parse_money("123,45") == Decimal("123.45")

    def should_parse_english_format(self):
        assert parse_money("1,234.56") == Decimal("1234.56")
        assert parse_money("-1,234.56") == Decimal("-1234.56")
        assert parse_money("123.45") == Decimal("123.45")

    def should_parse_with_currency_symbols(self):
        assert parse_money("€123.45") == Decimal("123.45")
        assert parse_money("-€123.45") == Decimal("-123.45")
        assert parse_money("$1,234.56") == Decimal("1234.56")
        assert parse_money("£99.99") == Decimal("99.99")

    def should_parse_parentheses_notation(self):
        assert parse_money("(123.45)") == Decimal("-123.45")
        assert parse_money("(1,234.56)") == Decimal("-1234.56")

    def should_handle_zero_and_dashes(self):
        assert parse_money("0") == Decimal("0")
        assert parse_money("0.00") == Decimal("0")
        assert parse_money("--") == Decimal("0")
        assert parse_money("") == Decimal("0")

    def should_handle_spaces(self):
        assert parse_money("  123.45  ") == Decimal("123.45")
        assert parse_money("€ 123.45") == Decimal("123.45")

    def should_reject_invalid_amounts(self):
        with pytest.raises(ValueError):
            parse_money("not a number")


class TestDateParsing:
    """Tests for parse_localized_date() function."""

    def should_parse_etsy_format(self):
        assert parse_localized_date("31. January 2026") == date(2026, 1, 31)
        assert parse_localized_date("1. February 2026") == date(2026, 2, 1)

    def should_parse_german_month_names(self):
        assert parse_localized_date("31. Januar 2026") == date(2026, 1, 31)
        assert parse_localized_date("15. März 2026") == date(2026, 3, 15)
        assert parse_localized_date("1. Dezember 2025") == date(2025, 12, 1)

    def should_parse_iso_format(self):
        assert parse_localized_date("2026-01-31") == date(2026, 1, 31)

    def should_parse_german_short_format(self):
        assert parse_localized_date("31.01.2026") == date(2026, 1, 31)
        assert parse_localized_date("01.12.2025") == date(2025, 12, 1)

    def should_parse_us_format(self):
        assert parse_localized_date("January 31, 2026") == date(2026, 1, 31)

    def should_reject_invalid_dates(self):
        with pytest.raises(ValueError):
            parse_localized_date("not a date")

        with pytest.raises(ValueError):
            parse_localized_date("")


class TestOrderIdExtraction:
    """Tests for extract_order_id() function."""

    def should_extract_order_number_english(self):
        assert extract_order_id("Order #3964911563", "Payment for order") == "3964911563"
        assert extract_order_id("", "Order #3964911563: Widget") == "3964911563"

    def should_extract_order_number_german(self):
        assert extract_order_id("Bestellnr. 3964911563", "") == "3964911563"
        assert extract_order_id("", "Bestellnr 3964911563") == "3964911563"

    def should_extract_standalone_hash_number(self):
        assert extract_order_id("#3964911563", "") == "3964911563"
        assert extract_order_id("", "#3964911563") == "3964911563"

    def should_return_none_for_short_numbers(self):
        # Less than 8 digits — not an order ID
        assert extract_order_id("#12345", "") is None

    def should_return_none_when_no_order_id(self):
        assert extract_order_id("Processing fee", "Zahlungsabwicklung") is None
        assert extract_order_id("", "") is None


class TestEncodingDetection:
    """Tests for sniff_encoding() function."""

    def should_detect_utf8_with_bom(self):
        content = b"\xef\xbb\xbfDatum,Art,Titel\n"
        assert sniff_encoding(content) == "utf-8-sig"

    def should_detect_utf8(self):
        content = "Datum,Art,Titel,Gebühren\n".encode("utf-8")
        assert sniff_encoding(content) == "utf-8"

    def should_detect_windows_1252(self):
        # Windows-1252 specific character: ü (0xFC)
        content = b"Datum,Art,Titel,Geb\xfchren\n"
        assert sniff_encoding(content) == "windows-1252"


class TestDelimiterDetection:
    """Tests for sniff_delimiter() function."""

    def should_detect_comma(self):
        line = "Datum,Art,Titel,Info,Währung,Betrag"
        assert sniff_delimiter(line) == ","

    def should_detect_semicolon(self):
        line = "Datum;Art;Titel;Info;Währung;Betrag"
        assert sniff_delimiter(line) == ";"

    def should_detect_tab(self):
        line = "Datum\tArt\tTitel\tInfo\tWährung\tBetrag"
        assert sniff_delimiter(line) == "\t"


class TestHeaderNormalization:
    """Tests for normalize_headers() function."""

    def should_normalize_german_headers(self):
        headers = ["Datum", "Art", "Titel", "Info", "Währung", "Betrag", "Gebühren & Steuern", "Netto", "Steuerliche Angaben"]
        result = normalize_headers(headers)

        assert result[COL_DATE] == 0
        assert result[COL_TYPE] == 1
        assert result[COL_TITLE] == 2
        assert result[COL_INFO] == 3
        assert result[COL_AMOUNT] == 5
        assert result[COL_NET] == 7

    def should_normalize_english_headers(self):
        headers = ["Date", "Type", "Title", "Info", "Currency", "Amount", "Fees & Taxes", "Net", "Taxes"]
        result = normalize_headers(headers)

        assert result[COL_DATE] == 0
        assert result[COL_TYPE] == 1
        assert result[COL_TITLE] == 2


class TestImportHash:
    """Tests for compute_etsy_import_hash() function."""

    def should_compute_deterministic_hash(self):
        hash1 = compute_etsy_import_hash(
            source_config_id="abc-123",
            transaction_date=date(2026, 1, 31),
            etsy_type=EtsyTransactionType.SALE,
            amount=Decimal("43.24"),
            order_id="3964911563",
            title="Payment for Order #3964911563",
        )
        hash2 = compute_etsy_import_hash(
            source_config_id="abc-123",
            transaction_date=date(2026, 1, 31),
            etsy_type=EtsyTransactionType.SALE,
            amount=Decimal("43.24"),
            order_id="3964911563",
            title="Payment for Order #3964911563",
        )
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def should_differ_by_source(self):
        hash1 = compute_etsy_import_hash("source-1", date(2026, 1, 31), EtsyTransactionType.SALE, Decimal("100"), "123", "title")
        hash2 = compute_etsy_import_hash("source-2", date(2026, 1, 31), EtsyTransactionType.SALE, Decimal("100"), "123", "title")
        assert hash1 != hash2

    def should_differ_by_type(self):
        hash1 = compute_etsy_import_hash("source-1", date(2026, 1, 31), EtsyTransactionType.SALE, Decimal("100"), "123", "title")
        hash2 = compute_etsy_import_hash("source-1", date(2026, 1, 31), EtsyTransactionType.FEE_PROCESSING, Decimal("100"), "123", "title")
        assert hash1 != hash2

    def should_differ_by_title_for_listing_fees(self):
        """Multiple listing fees on same day with same amount need title to differentiate."""
        hash1 = compute_etsy_import_hash(
            "source-1", date(2026, 1, 31), EtsyTransactionType.FEE_LISTING, Decimal("0.18"), None, "Listing fee for Widget A"
        )
        hash2 = compute_etsy_import_hash(
            "source-1", date(2026, 1, 31), EtsyTransactionType.FEE_LISTING, Decimal("0.18"), None, "Listing fee for Widget B"
        )
        assert hash1 != hash2


class TestEtsyStatementParser:
    """Integration tests for EtsyStatementParser class."""

    def should_parse_minimal_csv(self):
        csv_content = b"""Datum,Art,Titel,Info,W\xc3\xa4hrung,Betrag,Geb\xc3\xbchren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Sale,Payment for Order #3964911563,Order #3964911563,EUR,43.24,--,43.24,--
31. January 2026,Fee,Transaction fee: Shipping,Order #3964911563,EUR,-0.94,--,-0.94,--
"""
        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 2
        assert len(result.errors) == 0

        # Check sale row
        sale = result.rows[0]
        assert sale.etsy_type == EtsyTransactionType.SALE
        assert sale.amount == Decimal("43.24")
        assert sale.date == date(2026, 1, 31)
        assert sale.suggested_skr03 == 8195  # Kleinunternehmer
        assert sale.order_id == "3964911563"

        # Check fee row
        fee = result.rows[1]
        assert fee.etsy_type == EtsyTransactionType.FEE_TRANSACTION_SHIPPING
        assert fee.amount == Decimal("-0.94")
        assert fee.suggested_skr03 == 3165  # §13b ohne VSt

    def should_parse_csv_with_german_dates(self):
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. Januar 2026,Sale,Zahlung für Bestellung,Bestellnr. 12345678,EUR,100.00,--,100.00,--
""".encode("utf-8")

        parser = EtsyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 1
        assert result.rows[0].date == date(2026, 1, 31)

    def should_parse_payout_with_amount_in_title(self):
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Überweisung,€195.32 an dein Bankkonto überwiesen,,EUR,--,--,--,--
""".encode("utf-8")

        parser = EtsyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 1
        payout = result.rows[0]
        assert payout.etsy_type == EtsyTransactionType.PAYOUT
        assert payout.amount == Decimal("195.32")
        assert payout.is_internal_transfer is True
        assert payout.suggested_skr03 == 1360

    def should_handle_semicolon_delimiter(self):
        csv_content = """Datum;Art;Titel;Info;Währung;Betrag;Gebühren & Steuern;Netto;Steuerliche Angaben
31. January 2026;Sale;Payment for Order;Order #123;EUR;50.00;--;50.00;--
""".encode("utf-8")

        parser = EtsyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 1
        assert result.rows[0].amount == Decimal("50.00")

    def should_skip_inline_headers(self):
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Sale,Payment,Order #1,EUR,100.00,--,100.00,--
Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
1. February 2026,Sale,Payment,Order #2,EUR,200.00,--,200.00,--
""".encode("utf-8")

        parser = EtsyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 2
        assert result.skipped_rows >= 1

    def should_set_extra_data_for_marketplace(self):
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Fee,Processing fee,Order #3964911563,EUR,-1.23,--,-1.23,--
""".encode("utf-8")

        parser = EtsyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 1
        row = result.rows[0]
        assert row.extra_data["marketplace"] == "etsy"
        assert row.extra_data["marketplace_type"] == "fee_processing"
        assert row.extra_data["order_id"] == "3964911563"

    def should_use_regelbesteuert_accounts_when_configured(self):
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Sale,Payment,Order #1,EUR,100.00,--,100.00,--
31. January 2026,Fee,Processing fee,Order #1,EUR,-5.00,--,-5.00,--
""".encode("utf-8")

        parser = EtsyStatementParser(is_kleinunternehmer=False, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert result.rows[0].suggested_skr03 == 8400  # Regelbesteuert Erlöse
        assert result.rows[1].suggested_skr03 == 3125  # §13b mit VSt

    def should_use_brutto_accounts_without_ust_id(self):
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Fee,Processing fee,Order #1,EUR,-5.00,--,-5.00,--
""".encode("utf-8")

        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=False)
        result = parser.parse(csv_content, "test-source-id")

        assert result.rows[0].suggested_skr03 == 4761  # Brutto, no RC

    def should_reject_csv_without_required_columns(self):
        csv_content = """Name,Value
Test,123
""".encode("utf-8")

        parser = EtsyStatementParser()
        with pytest.raises(EtsyParseError) as exc_info:
            parser.parse(csv_content, "test-source-id")

        assert "Missing required columns" in str(exc_info.value)

    def should_handle_malformed_rows_gracefully(self):
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Sale,Payment,Order #1,EUR,100.00,--,100.00,--
invalid date,Sale,Payment,Order #2,EUR,50.00,--,50.00,--
1. February 2026,Sale,Payment,Order #3,EUR,75.00,--,75.00,--
""".encode("utf-8")

        parser = EtsyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        # Should parse 2 valid rows, 1 error
        assert len(result.rows) == 2
        assert len(result.errors) == 1
        assert "Row 3" in result.errors[0]

    def should_build_source_reference_with_type_suffix(self):
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Sale,Payment,Order #123,EUR,100.00,--,100.00,--
31. January 2026,Fee,Processing fee,Order #123,EUR,-5.00,--,-5.00,--
31. January 2026,Tax,Sales tax paid by buyer,Order #123,EUR,-8.00,--,-8.00,--
""".encode("utf-8")

        parser = EtsyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert result.rows[0].source_reference == "Order #123"
        assert result.rows[1].source_reference == "Order #123_FEE_PROCESSING"
        assert result.rows[2].source_reference == "Order #123_TAX"


class TestSpecialCases:
    """Tests for Phase 3: Refunds, Tax, Credits, Payouts special handling."""

    def should_parse_refund_with_negative_amount(self):
        """EC-1: Refunds reduce revenue and appear with negative amounts."""
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
15. October 2025,Refund,Refund for Order #3827903039,Order #3827903039,EUR,-21.90,--,-21.90,--
""".encode("utf-8")

        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 1
        refund = result.rows[0]
        assert refund.etsy_type == EtsyTransactionType.REFUND
        assert refund.amount == Decimal("-21.90")  # Negative = reduces revenue
        assert refund.suggested_skr03 == 8195  # Same as sale (Erlösminderung)
        assert refund.source_reference == "Order #3827903039_REFUND"
        assert refund.is_internal_transfer is False  # Affects revenue, not pass-through
        assert refund.order_id == "3827903039"
        assert "Rückerstattung" in refund.description

    def should_parse_credit_with_positive_amount(self):
        """EC-1: Fee credits reverse original fees and appear with positive amounts."""
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
15. October 2025,Fee,Credit for transaction fee,Order #3827903039,EUR,1.17,--,1.17,--
15. October 2025,Fee,Credit for processing fee,Order #3827903039,EUR,1.18,--,1.18,--
15. October 2025,Fee,Gutschrift für Einstellgebühr,Order #3827903039,EUR,0.17,--,0.17,--
""".encode("utf-8")

        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 3

        # Credit for transaction fee
        credit_tx = result.rows[0]
        assert credit_tx.etsy_type == EtsyTransactionType.CREDIT_TRANSACTION
        assert credit_tx.amount == Decimal("1.17")  # Positive = reverses fee
        assert credit_tx.suggested_skr03 == 3165  # Same as fee (RC-eligible)
        assert credit_tx.source_reference == "Order #3827903039_CREDIT_TRANSACTION"
        assert credit_tx.is_internal_transfer is False

        # Credit for processing fee
        credit_proc = result.rows[1]
        assert credit_proc.etsy_type == EtsyTransactionType.CREDIT_PROCESSING
        assert credit_proc.amount == Decimal("1.18")
        assert credit_proc.source_reference == "Order #3827903039_CREDIT_PROCESSING"

        # Credit for listing fee (German)
        credit_list = result.rows[2]
        assert credit_list.etsy_type == EtsyTransactionType.CREDIT_LISTING
        assert credit_list.amount == Decimal("0.17")
        assert credit_list.source_reference == "Order #3827903039_CREDIT_LISTING"

    def should_parse_sales_tax_as_internal_transfer(self):
        """EC-2: Sales tax is durchlaufender Posten (pass-through, not seller's revenue)."""
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
10. October 2025,Tax,Sales tax paid by buyer,Order #3839381052,EUR,-3.24,--,-3.24,--
""".encode("utf-8")

        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 1
        tax = result.rows[0]
        assert tax.etsy_type == EtsyTransactionType.SALES_TAX
        assert tax.amount == Decimal("-3.24")  # Negative (tax deducted from clearing account)
        assert tax.suggested_skr03 == 1590  # Durchlaufende Posten
        assert tax.source_reference == "Order #3839381052_TAX"
        assert tax.is_internal_transfer is True  # NOT revenue, erfolgsneutral
        assert tax.order_id == "3839381052"

    def should_parse_complete_refund_scenario(self):
        """EC-1: Full refund with all fee credits — net effect = 0."""
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
15. October 2025,Refund,Refund for Order #3827903039,Order #3827903039,EUR,-21.90,--,-21.90,--
15. October 2025,Fee,Credit for transaction fee: Item,Order #3827903039,EUR,1.17,--,1.17,--
15. October 2025,Fee,Credit for transaction fee: Shipping,Order #3827903039,EUR,0.25,--,0.25,--
15. October 2025,Fee,Credit for processing fee,Order #3827903039,EUR,1.18,--,1.18,--
15. October 2025,Fee,Credit for listing fee,Order #3827903039,EUR,0.17,--,0.17,--
""".encode("utf-8")

        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 5

        # Verify refund
        refund = result.rows[0]
        assert refund.etsy_type == EtsyTransactionType.REFUND
        assert refund.amount == Decimal("-21.90")

        # Sum of credits
        credits_total = sum(row.amount for row in result.rows[1:])
        assert credits_total == Decimal("2.77")  # 1.17 + 0.25 + 1.18 + 0.17

        # All credits have same order ID
        assert all(row.order_id == "3827903039" for row in result.rows)

    def should_parse_october_2025_with_multiple_tax_orders(self):
        """EC-2: Multiple orders with Sales Tax (4 orders in October 2025)."""
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
5. October 2025,Sale,Payment for Order #3839381052,Order #3839381052,EUR,43.24,--,43.24,--
5. October 2025,Tax,Sales tax paid by buyer,Order #3839381052,EUR,-3.24,--,-3.24,--
6. October 2025,Sale,Payment for Order #3838841689,Order #3838841689,EUR,29.73,--,29.73,--
6. October 2025,Tax,Sales tax paid by buyer,Order #3838841689,EUR,-2.23,--,-2.23,--
7. October 2025,Sale,Payment for Order #3834327403,Order #3834327403,EUR,33.51,--,33.51,--
7. October 2025,Tax,Sales tax paid by buyer,Order #3834327403,EUR,-2.51,--,-2.51,--
8. October 2025,Sale,Payment for Order #3821248803,Order #3821248803,EUR,24.86,--,24.86,--
8. October 2025,Tax,Sales tax paid by buyer,Order #3821248803,EUR,-1.86,--,-1.86,--
""".encode("utf-8")

        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 8

        # 4 sales, 4 taxes
        sales = [r for r in result.rows if r.etsy_type == EtsyTransactionType.SALE]
        taxes = [r for r in result.rows if r.etsy_type == EtsyTransactionType.SALES_TAX]
        assert len(sales) == 4
        assert len(taxes) == 4

        # All sales are NOT internal transfers
        assert all(s.is_internal_transfer is False for s in sales)

        # All taxes ARE internal transfers (durchlaufend)
        assert all(t.is_internal_transfer is True for t in taxes)

        # Total tax = 9.84€ (as in EC-2)
        total_tax = sum(t.amount for t in taxes)
        assert total_tax == Decimal("-9.84")

        # Net revenue = Sales - Tax = actual revenue
        total_sales = sum(s.amount for s in sales)
        expected_net = total_sales + total_tax  # tax is negative
        # 43.24+29.73+33.51+24.86 - 9.84 = 121.50
        assert expected_net == Decimal("121.50")

    def should_parse_payout_from_title_with_german_format(self):
        """Payout amount extracted from German-formatted title (with comma as decimal)."""
        # Note: CSV field with comma must be quoted
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
6. October 2025,Überweisung,"€826,34 an dein Bankkonto überwiesen",,EUR,--,--,--,--
""".encode("utf-8")

        parser = EtsyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 1
        payout = result.rows[0]
        assert payout.etsy_type == EtsyTransactionType.PAYOUT
        assert payout.amount == Decimal("826.34")
        assert payout.is_internal_transfer is True
        assert payout.source_reference == "Payout_2025-10-06"
        assert payout.suggested_skr03 == 1360

    def should_set_correct_counterparty_for_special_types(self):
        """Verify counterparty is set correctly for each type."""
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
1. January 2026,Sale,Payment for Order #123,Order #123,EUR,50.00,--,50.00,--
1. January 2026,Refund,Refund for Order #456,Order #456,EUR,-30.00,--,-30.00,--
1. January 2026,Tax,Sales tax paid by buyer,Order #789,EUR,-5.00,--,-5.00,--
1. January 2026,Fee,Processing fee,Order #123,EUR,-2.50,--,-2.50,--
1. January 2026,Überweisung,€100.00 an dein Bankkonto überwiesen,,EUR,--,--,--,--
""".encode("utf-8")

        parser = EtsyStatementParser()
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 5

        sale = result.rows[0]
        assert sale.counterparty == "Etsy Kunde"

        refund = result.rows[1]
        assert refund.counterparty == "Etsy Kunde"  # Refund also to customer

        tax = result.rows[2]
        # Tax is handled by Etsy as Marketplace Facilitator
        assert tax.counterparty == "Etsy Ireland UC"

        fee = result.rows[3]
        assert fee.counterparty == "Etsy Ireland UC"

        payout = result.rows[4]
        assert payout.counterparty == "Etsy Auszahlung"


class TestReverseChargeCalculation:
    """Tests for §13b Reverse Charge calculation fields (Council-Amendment #1).

    These tests verify that rc_fee_amount is set at parse time, NOT calculated
    from abs(amount). This prevents the RC-Bug where sale amounts would be
    incorrectly included in the RC base.
    """

    def should_set_rc_fee_amount_for_fee_rows(self):
        """Fee rows with USt-ID should have rc_fee_amount = abs(amount)."""
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Fee,Processing fee,Order #1,EUR,-5.00,--,-5.00,--
31. January 2026,Fee,Transaction fee: Shipping,Order #1,EUR,-0.94,--,-0.94,--
""".encode("utf-8")

        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 2
        assert result.rows[0].is_rc_eligible is True
        assert result.rows[0].rc_fee_amount == Decimal("5.00")
        assert result.rows[1].is_rc_eligible is True
        assert result.rows[1].rc_fee_amount == Decimal("0.94")

    def should_not_set_rc_fee_amount_for_sale_rows(self):
        """Sale rows should have rc_fee_amount = 0 (sales are NOT RC-eligible)."""
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Sale,Payment for Order #1,Order #1,EUR,100.00,--,100.00,--
""".encode("utf-8")

        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 1
        assert result.rows[0].is_rc_eligible is False
        assert result.rows[0].rc_fee_amount == Decimal("0")

    def should_not_set_rc_for_fees_without_ust_id(self):
        """Without USt-ID, no RC applies even for fee rows."""
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Fee,Processing fee,Order #1,EUR,-5.00,--,-5.00,--
""".encode("utf-8")

        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=False)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 1
        assert result.rows[0].is_rc_eligible is False
        assert result.rows[0].rc_fee_amount == Decimal("0")

    def should_calculate_correct_rc_base_for_mixed_rows(self):
        """RC base must be sum(rc_fee_amount), NOT sum(abs(amount)).

        This is the key regression test: The old buggy calculation summed
        abs(amount) which would incorrectly include sale amounts in the RC base.
        """
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Sale,Payment for Order #1,Order #1,EUR,100.00,--,100.00,--
31. January 2026,Fee,Processing fee,Order #1,EUR,-5.00,--,-5.00,--
31. January 2026,Fee,Transaction fee: Item,Order #1,EUR,-2.50,--,-2.50,--
31. January 2026,Refund,Refund for Order #2,Order #2,EUR,-30.00,--,-30.00,--
""".encode("utf-8")

        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 4

        # Calculate both sums
        rc_fee_sum = sum(row.rc_fee_amount for row in result.rows)
        abs_amount_sum = sum(abs(row.amount) for row in result.rows)

        # RC base should be ONLY fees: 5.00 + 2.50 = 7.50
        assert rc_fee_sum == Decimal("7.50")

        # abs(amount) sum would be: 100 + 5 + 2.50 + 30 = 137.50 (WRONG!)
        assert abs_amount_sum == Decimal("137.50")

        # The key assertion: these must be different
        assert rc_fee_sum != abs_amount_sum, "RC base must NOT equal sum(abs(amount)) for mixed rows"

    def should_include_credits_and_marketing_in_rc_base(self):
        """Credits and marketing fees are also RC-eligible."""
        csv_content = """Datum,Art,Titel,Info,Währung,Betrag,Gebühren & Steuern,Netto,Steuerliche Angaben
31. January 2026,Fee,Credit for processing fee,Order #1,EUR,1.00,--,1.00,--
31. January 2026,Fee,Etsy Ads,Order #1,EUR,-10.00,--,-10.00,--
31. January 2026,Fee,Offsite Ads,Order #1,EUR,-3.00,--,-3.00,--
""".encode("utf-8")

        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(csv_content, "test-source-id")

        assert len(result.rows) == 3

        # Credit (positive amount)
        credit = result.rows[0]
        assert credit.etsy_type == EtsyTransactionType.CREDIT_PROCESSING
        assert credit.is_rc_eligible is True
        assert credit.rc_fee_amount == Decimal("1.00")

        # Etsy Ads
        ads = result.rows[1]
        assert ads.etsy_type == EtsyTransactionType.MARKETING_ADS
        assert ads.is_rc_eligible is True
        assert ads.rc_fee_amount == Decimal("10.00")

        # Offsite Ads
        offsite = result.rows[2]
        assert offsite.etsy_type == EtsyTransactionType.MARKETING_OFFSITE
        assert offsite.is_rc_eligible is True
        assert offsite.rc_fee_amount == Decimal("3.00")

        # Total RC base
        rc_fee_sum = sum(row.rc_fee_amount for row in result.rows)
        assert rc_fee_sum == Decimal("14.00")
