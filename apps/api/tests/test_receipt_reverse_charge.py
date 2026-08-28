"""Tests for Reverse Charge (§13b UStG) functionality on receipts."""

from decimal import Decimal

from app.models.receipt import Receipt, ReceiptStatus, ReceiptType
from app.models.receipt_line_item import ReceiptLineItem, TaxRule

from tests.conftest import AUTH_HEADERS


class TestTaxRuleEnum:
    """Tests for TaxRule enum and helper methods."""

    def should_identify_reverse_charge_variants(self) -> None:
        rc_rules = [
            TaxRule.REVERSE_CHARGE,
            TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX,
            TaxRule.REVERSE_CHARGE_EU_WITH_INPUT_TAX,
            TaxRule.REVERSE_CHARGE_DE_NO_INPUT_TAX,
            TaxRule.REVERSE_CHARGE_DE_WITH_INPUT_TAX,
            TaxRule.REVERSE_CHARGE_NON_EU_NO_INPUT_TAX,
            TaxRule.REVERSE_CHARGE_NON_EU_WITH_INPUT_TAX,
        ]
        for rule in rc_rules:
            assert rule.is_reverse_charge(), f"{rule} should be reverse charge"

    def should_identify_non_reverse_charge_rules(self) -> None:
        for rule in [TaxRule.TAX_INCLUDED, TaxRule.TAX_EXCLUDED, TaxRule.NO_TAX]:
            assert not rule.is_reverse_charge(), f"{rule} should NOT be reverse charge"

    def should_identify_input_tax_claimable(self) -> None:
        assert TaxRule.REVERSE_CHARGE_EU_WITH_INPUT_TAX.has_input_tax()
        assert TaxRule.REVERSE_CHARGE_DE_WITH_INPUT_TAX.has_input_tax()
        assert TaxRule.REVERSE_CHARGE_NON_EU_WITH_INPUT_TAX.has_input_tax()
        assert not TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX.has_input_tax()
        assert not TaxRule.REVERSE_CHARGE_DE_NO_INPUT_TAX.has_input_tax()
        assert not TaxRule.REVERSE_CHARGE_NON_EU_NO_INPUT_TAX.has_input_tax()
        assert not TaxRule.REVERSE_CHARGE.has_input_tax()

    def should_return_bu_94_for_with_input_tax(self) -> None:
        assert TaxRule.REVERSE_CHARGE_EU_WITH_INPUT_TAX.bu_schluessel() == 94
        assert TaxRule.REVERSE_CHARGE_DE_WITH_INPUT_TAX.bu_schluessel() == 94
        assert TaxRule.REVERSE_CHARGE_NON_EU_WITH_INPUT_TAX.bu_schluessel() == 94

    def should_return_bu_95_for_no_input_tax(self) -> None:
        assert TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX.bu_schluessel() == 95
        assert TaxRule.REVERSE_CHARGE_DE_NO_INPUT_TAX.bu_schluessel() == 95
        assert TaxRule.REVERSE_CHARGE_NON_EU_NO_INPUT_TAX.bu_schluessel() == 95
        assert TaxRule.REVERSE_CHARGE.bu_schluessel() == 95

    def should_return_none_bu_for_non_rc(self) -> None:
        assert TaxRule.TAX_INCLUDED.bu_schluessel() is None
        assert TaxRule.NO_TAX.bu_schluessel() is None

    def should_suggest_3125_for_with_input_tax(self) -> None:
        assert TaxRule.REVERSE_CHARGE_EU_WITH_INPUT_TAX.suggested_skr03_account() == 3125
        assert TaxRule.REVERSE_CHARGE_DE_WITH_INPUT_TAX.suggested_skr03_account() == 3125
        assert TaxRule.REVERSE_CHARGE_NON_EU_WITH_INPUT_TAX.suggested_skr03_account() == 3125

    def should_suggest_3165_for_no_input_tax(self) -> None:
        assert TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX.suggested_skr03_account() == 3165
        assert TaxRule.REVERSE_CHARGE_DE_NO_INPUT_TAX.suggested_skr03_account() == 3165
        assert TaxRule.REVERSE_CHARGE_NON_EU_NO_INPUT_TAX.suggested_skr03_account() == 3165

    def should_suggest_none_for_non_rc(self) -> None:
        assert TaxRule.TAX_INCLUDED.suggested_skr03_account() is None


def _create_receipt_with_items(
    session,
    user_id: str,
    items: list[tuple[Decimal, TaxRule]],
    counterparty: str = "Etsy Ireland UC",
) -> Receipt:
    """Helper: create receipt with line items."""
    receipt = Receipt(
        user_id=user_id,
        type=ReceiptType.EXPENSE,
        receipt_number="TEST-001",
        date="2026-01-31",
        counterparty=counterparty,
        status=ReceiptStatus.DRAFT,
    )
    session.add(receipt)
    session.flush()

    for position, (amount, tax_rule) in enumerate(items):
        line = ReceiptLineItem(
            receipt_id=receipt.id,
            position=position,
            description=f"Item {position}",
            amount=amount,
            tax_rule=tax_rule,
            tax_rate=Decimal("19.00"),
        )
        session.add(line)

    session.flush()
    session.refresh(receipt)
    return receipt


class TestReceiptLineItemReverseCharge:
    """Tests for RC tax calculations on ReceiptLineItem."""

    def should_calculate_rc_tax_for_etsy_kleinunternehmer(self, seeded_session, example_user) -> None:
        """241.66€ × 19% = 45.92€ (real Etsy January 2026 fees)."""
        receipt = _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [(Decimal("241.66"), TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX)],
        )
        assert receipt.line_items[0].reverse_charge_tax_amount == Decimal("45.92")

    def should_calculate_rc_tax_for_regelbesteuert(self, seeded_session, example_user) -> None:
        receipt = _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [(Decimal("100.00"), TaxRule.REVERSE_CHARGE_EU_WITH_INPUT_TAX)],
        )
        assert receipt.line_items[0].reverse_charge_tax_amount == Decimal("19.00")

    def should_return_none_for_non_rc(self, seeded_session, example_user) -> None:
        receipt = _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [(Decimal("100.00"), TaxRule.TAX_INCLUDED)],
        )
        assert receipt.line_items[0].reverse_charge_tax_amount is None

    def should_use_absolute_amount(self, seeded_session, example_user) -> None:
        """RC tax uses absolute amount (for credits/negatives)."""
        receipt = _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [(Decimal("-100.00"), TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX)],
        )
        assert receipt.line_items[0].reverse_charge_tax_amount == Decimal("19.00")

    def should_return_19_percent_effective_rate_for_rc(self, seeded_session, example_user) -> None:
        receipt = _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [(Decimal("100.00"), TaxRule.REVERSE_CHARGE_NON_EU_WITH_INPUT_TAX)],
        )
        assert receipt.line_items[0].effective_tax_rate == Decimal("19.00")

    def should_preserve_stored_rate_for_non_rc(self, seeded_session, example_user) -> None:
        receipt = _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [(Decimal("100.00"), TaxRule.TAX_INCLUDED)],
        )
        receipt.line_items[0].tax_rate = Decimal("7.00")
        assert receipt.line_items[0].effective_tax_rate == Decimal("7.00")


class TestReceiptReverseChargeAggregates:
    """Tests for RC aggregates on Receipt model."""

    def should_calculate_total_rc_tax(self, seeded_session, example_user) -> None:
        """100×19% + 50×19% = 19 + 9.50 = 28.50 (non-RC items excluded)."""
        receipt = _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [
                (Decimal("100.00"), TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX),
                (Decimal("50.00"), TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX),
                (Decimal("30.00"), TaxRule.TAX_INCLUDED),  # Not RC
            ],
        )
        assert receipt.total_reverse_charge_tax == Decimal("28.50")

    def should_calculate_total_amount(self, seeded_session, example_user) -> None:
        receipt = _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [
                (Decimal("100.00"), TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX),
                (Decimal("50.00"), TaxRule.TAX_INCLUDED),
            ],
        )
        assert receipt.total_amount == Decimal("150.00")

    def should_detect_rc_items(self, seeded_session, example_user) -> None:
        receipt = _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [
                (Decimal("100.00"), TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX),
                (Decimal("50.00"), TaxRule.TAX_INCLUDED),
            ],
        )
        assert receipt.has_reverse_charge_items is True

    def should_detect_no_rc_items(self, seeded_session, example_user) -> None:
        receipt = _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [(Decimal("100.00"), TaxRule.TAX_INCLUDED)],
        )
        assert receipt.has_reverse_charge_items is False
        assert receipt.total_reverse_charge_tax == Decimal("0.00")


class TestReverseChargeApiResponse:
    """Tests for RC fields in API responses."""

    def should_include_rc_fields_in_receipt_response(self, api_client, seeded_session) -> None:
        receipt = Receipt(
            user_id="test-user-id",
            type=ReceiptType.EXPENSE,
            receipt_number="API-RC-001",
            date="2026-01-31",
            counterparty="Etsy Ireland UC",
            status=ReceiptStatus.DRAFT,
        )
        seeded_session.add(receipt)
        seeded_session.flush()

        line = ReceiptLineItem(
            receipt_id=receipt.id,
            position=0,
            description="Etsy Fees",
            amount=Decimal("100.00"),
            tax_rule=TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX,
            tax_rate=Decimal("19.00"),
        )
        seeded_session.add(line)
        seeded_session.commit()

        response = api_client.get(f"/api/v1/receipts/{receipt.id}", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()

        # Receipt-level RC aggregates
        assert data["has_reverse_charge_items"] is True
        assert Decimal(data["total_reverse_charge_tax"]) == Decimal("19.00")

        # Line item RC fields
        line_data = data["line_items"][0]
        assert Decimal(line_data["reverse_charge_tax_amount"]) == Decimal("19.00")
        assert Decimal(line_data["effective_tax_rate"]) == Decimal("19.00")
        assert line_data["tax_rule"] == "rc_eu_no_vst"

    def should_return_zero_rc_for_non_rc_receipt(self, api_client, seeded_session) -> None:
        receipt = Receipt(
            user_id="test-user-id",
            type=ReceiptType.EXPENSE,
            receipt_number="API-NORC-001",
            date="2026-01-31",
            counterparty="Normal Supplier",
            status=ReceiptStatus.DRAFT,
        )
        seeded_session.add(receipt)
        seeded_session.flush()

        line = ReceiptLineItem(
            receipt_id=receipt.id,
            position=0,
            description="Office supplies",
            amount=Decimal("50.00"),
            tax_rule=TaxRule.TAX_INCLUDED,
            tax_rate=Decimal("19.00"),
        )
        seeded_session.add(line)
        seeded_session.commit()

        response = api_client.get(f"/api/v1/receipts/{receipt.id}", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()

        assert data["has_reverse_charge_items"] is False
        assert Decimal(data["total_reverse_charge_tax"]) == Decimal("0")
        assert data["line_items"][0]["reverse_charge_tax_amount"] is None


class TestRCComplianceEndpoint:
    """Tests for the /api/v1/receipts/rc-compliance endpoint (UStVA compliance hint)."""

    def should_return_empty_summary_when_no_rc_items(self, api_client, seeded_session, example_user) -> None:
        """No RC items → summary shows has_rc_items=False."""
        # Create a non-RC receipt
        receipt = Receipt(
            user_id=example_user.id,
            type=ReceiptType.EXPENSE,
            receipt_number="NO-RC-001",
            date="2026-01-15",
            counterparty="Regular Supplier",
            status=ReceiptStatus.DRAFT,
        )
        seeded_session.add(receipt)
        seeded_session.flush()

        line = ReceiptLineItem(
            receipt_id=receipt.id,
            position=0,
            description="Normal purchase",
            amount=Decimal("100.00"),
            tax_rule=TaxRule.TAX_INCLUDED,
            tax_rate=Decimal("19.00"),
        )
        seeded_session.add(line)
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/receipts/rc-compliance",
            params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["has_rc_items"] is False
        assert Decimal(data["rc_net_total"]) == Decimal("0.00")
        assert Decimal(data["rc_tax_total"]) == Decimal("0.00")
        assert data["rc_item_count"] == 0

    def should_calculate_rc_totals_for_kleinunternehmer(self, api_client, seeded_session, example_user) -> None:
        """Kleinunternehmer RC items → Kz.46/47 calculated, Kz.67 = 0."""
        from app.models.site_settings import SiteSettings

        # Set site to Kleinunternehmer
        site_settings = seeded_session.query(SiteSettings).first()
        if site_settings:
            site_settings.is_small_business = True
        seeded_session.commit()

        # Create RC receipt (Etsy fees)
        receipt = Receipt(
            user_id=example_user.id,
            type=ReceiptType.EXPENSE,
            receipt_number="ETSY-RC-001",
            date="2026-01-15",
            counterparty="Etsy Ireland UC",
            status=ReceiptStatus.DRAFT,
        )
        seeded_session.add(receipt)
        seeded_session.flush()

        # Two RC line items
        line1 = ReceiptLineItem(
            receipt_id=receipt.id,
            position=0,
            description="Transaction Fees",
            amount=Decimal("55.08"),
            tax_rule=TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX,  # Kleinunternehmer
            tax_rate=Decimal("19.00"),
        )
        line2 = ReceiptLineItem(
            receipt_id=receipt.id,
            position=1,
            description="Listing Fees",
            amount=Decimal("7.99"),
            tax_rule=TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX,
            tax_rate=Decimal("19.00"),
        )
        seeded_session.add(line1)
        seeded_session.add(line2)
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/receipts/rc-compliance",
            params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["has_rc_items"] is True
        assert data["rc_item_count"] == 2

        # Kz.46: 55.08 + 7.99 = 63.07
        assert Decimal(data["rc_net_total"]) == Decimal("63.07")

        # Kz.47: 63.07 × 19% = 11.98 (rounded)
        expected_tax = (Decimal("55.08") * Decimal("0.19")).quantize(Decimal("0.01")) + (Decimal("7.99") * Decimal("0.19")).quantize(Decimal("0.01"))
        assert Decimal(data["rc_tax_total"]) == expected_tax

        # Kz.67: 0 for Kleinunternehmer (no Vorsteuerabzug)
        assert Decimal(data["rc_input_tax_total"]) == Decimal("0.00")
        assert data["is_small_business"] is True
        assert data["period_label"] == "Januar 2026"

    def should_calculate_input_tax_for_regelbesteuert(self, api_client, seeded_session, example_user) -> None:
        """Regelbesteuert RC items → Kz.67 filled with input tax."""
        from app.models.site_settings import SiteSettings

        # Set site to Regelbesteuert
        site_settings = seeded_session.query(SiteSettings).first()
        if site_settings:
            site_settings.is_small_business = False
        seeded_session.commit()

        # Create RC receipt with input tax variant
        receipt = Receipt(
            user_id=example_user.id,
            type=ReceiptType.EXPENSE,
            receipt_number="ETSY-RC-RB",
            date="2026-02-15",
            counterparty="Etsy Ireland UC",
            status=ReceiptStatus.DRAFT,
        )
        seeded_session.add(receipt)
        seeded_session.flush()

        line = ReceiptLineItem(
            receipt_id=receipt.id,
            position=0,
            description="Transaction Fees",
            amount=Decimal("100.00"),
            tax_rule=TaxRule.REVERSE_CHARGE_EU_WITH_INPUT_TAX,  # Regelbesteuert
            tax_rate=Decimal("19.00"),
        )
        seeded_session.add(line)
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/receipts/rc-compliance",
            params={"date_from": "2026-02-01", "date_to": "2026-02-28"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["has_rc_items"] is True

        # Kz.46: 100.00
        assert Decimal(data["rc_net_total"]) == Decimal("100.00")

        # Kz.47: 19.00
        assert Decimal(data["rc_tax_total"]) == Decimal("19.00")

        # Kz.67: 19.00 for Regelbesteuert (Vorsteuerabzug)
        assert Decimal(data["rc_input_tax_total"]) == Decimal("19.00")
        assert data["is_small_business"] is False
        assert data["period_label"] == "Februar 2026"

    def should_filter_by_date_range(self, api_client, seeded_session, example_user) -> None:
        """RC items outside date range should not be included."""
        # Create RC receipt in January
        receipt = Receipt(
            user_id=example_user.id,
            type=ReceiptType.EXPENSE,
            receipt_number="RC-JAN",
            date="2026-01-15",
            counterparty="Etsy",
            status=ReceiptStatus.DRAFT,
        )
        seeded_session.add(receipt)
        seeded_session.flush()

        line = ReceiptLineItem(
            receipt_id=receipt.id,
            position=0,
            description="Fees",
            amount=Decimal("50.00"),
            tax_rule=TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX,
            tax_rate=Decimal("19.00"),
        )
        seeded_session.add(line)
        seeded_session.commit()

        # Query February → should find nothing
        response = api_client.get(
            "/api/v1/receipts/rc-compliance",
            params={"date_from": "2026-02-01", "date_to": "2026-02-28"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["has_rc_items"] is False
        assert data["rc_item_count"] == 0
