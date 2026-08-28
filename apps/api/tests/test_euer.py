"""Tests for EÜR (Einnahmen-Überschuss-Rechnung) summary endpoint."""

from decimal import Decimal

from app.models.receipt import Receipt, ReceiptStatus, ReceiptType
from app.models.receipt_line_item import ReceiptLineItem, TaxRule
from app.models.site_settings import SiteSettings

from tests.conftest import AUTH_HEADERS


def _create_receipt_with_items(
    session,
    user_id: str,
    items: list[tuple[Decimal, int, TaxRule]],  # (amount, skr03_account_id, tax_rule)
    receipt_type: ReceiptType = ReceiptType.EXPENSE,
    counterparty: str = "Test Counterparty",
    receipt_date: str = "2026-01-15",
) -> Receipt:
    """Helper: create receipt with line items on specific SKR03 accounts."""
    receipt = Receipt(
        user_id=user_id,
        type=receipt_type,
        receipt_number=f"TEST-{id(items)}",
        date=receipt_date,
        counterparty=counterparty,
        status=ReceiptStatus.FINAL,
    )
    session.add(receipt)
    session.flush()

    for i, (amount, account_id, tax_rule) in enumerate(items):
        item = ReceiptLineItem(
            receipt_id=receipt.id,
            position=i,
            description=f"Item {i + 1}",
            amount=amount,
            skr03_account_id=account_id,
            tax_rule=tax_rule,
        )
        session.add(item)

    session.flush()
    return receipt


class TestEuerSummaryEndpoint:
    """Tests for GET /api/v1/dashboard/euer-summary."""

    def should_return_empty_summary_for_no_data(self, api_client) -> None:
        """No receipts → all zeros."""
        response = api_client.get(
            "/api/v1/dashboard/euer-summary",
            params={"period_start": "2026-01-01", "period_end": "2026-01-31"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["revenue_total"] == "0.00"
        assert data["expense_total"] == "0.00"
        assert data["rc_tax_owed"] == "0.00"
        assert data["rc_input_tax"] == "0.00"
        assert data["profit"] == "0.00"

    def should_calculate_revenue_from_revenue_accounts(self, api_client, seeded_session, example_user) -> None:
        """Revenue account (8400) sums correctly."""
        # Create revenue receipt with 8400 (Erlöse 19%)
        _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [
                (Decimal("500.00"), 8400, TaxRule.TAX_INCLUDED),
                (Decimal("300.00"), 8400, TaxRule.TAX_INCLUDED),
            ],
            receipt_type=ReceiptType.REVENUE,
            receipt_date="2026-01-15",
        )
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/dashboard/euer-summary",
            params={"period_start": "2026-01-01", "period_end": "2026-01-31"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert Decimal(data["revenue_total"]) == Decimal("800.00")

    def should_calculate_expenses_from_expense_accounts(self, api_client, seeded_session, example_user) -> None:
        """Expense accounts (4xxx) sum correctly."""
        # Create expense receipt with 4761 (Etsy Gebühren)
        _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [
                (Decimal("100.00"), 4761, TaxRule.NO_TAX),  # Etsy fees
                (Decimal("50.00"), 4600, TaxRule.TAX_INCLUDED),  # Werbekosten
            ],
            receipt_type=ReceiptType.EXPENSE,
            receipt_date="2026-01-15",
        )
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/dashboard/euer-summary",
            params={"period_start": "2026-01-01", "period_end": "2026-01-31"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert Decimal(data["expense_total"]) == Decimal("150.00")

    def should_exclude_neutral_accounts_from_revenue_and_expense(self, api_client, seeded_session, example_user) -> None:
        """Neutral account (1590) excluded from EÜR (durchlaufende Posten)."""
        # Create receipts mixing accounts
        _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [
                (Decimal("100.00"), 8400, TaxRule.TAX_INCLUDED),  # Revenue → counted
                (Decimal("50.00"), 1590, TaxRule.NO_TAX),  # Neutral → excluded
            ],
            receipt_type=ReceiptType.REVENUE,
            receipt_date="2026-01-15",
        )
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/dashboard/euer-summary",
            params={"period_start": "2026-01-01", "period_end": "2026-01-31"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        # Only 8400 counted, 1590 excluded
        assert Decimal(data["revenue_total"]) == Decimal("100.00")

    def should_calculate_rc_tax_for_kleinunternehmer(self, api_client, seeded_session, example_user) -> None:
        """§13b-USt for Kleinunternehmer — real expense, no input tax offset."""
        # Set Kleinunternehmer status
        settings = seeded_session.query(SiteSettings).first()
        settings.is_small_business = True
        seeded_session.flush()

        # Create RC expense (Etsy fees with RC)
        _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [
                (Decimal("241.66"), 3165, TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX),  # RC without VSt
            ],
            receipt_type=ReceiptType.EXPENSE,
            counterparty="Etsy Ireland UC",
            receipt_date="2026-01-15",
        )
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/dashboard/euer-summary",
            params={"period_start": "2026-01-01", "period_end": "2026-01-31"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()

        # Net expense = 241.66
        assert Decimal(data["expense_total"]) == Decimal("241.66")

        # RC tax = 241.66 × 19% = 45.92 (Zeile 58)
        assert Decimal(data["rc_tax_owed"]) == Decimal("45.92")

        # No input tax for Kleinunternehmer (Zeile 57 = 0)
        assert Decimal(data["rc_input_tax"]) == Decimal("0.00")
        assert data["is_small_business"] is True

        # Profit impact: -241.66 (expense) - 45.92 (RC tax) = -287.58
        assert Decimal(data["profit"]) == Decimal("-287.58")

    def should_calculate_rc_tax_for_regelbesteuert(self, api_client, seeded_session, example_user) -> None:
        """§13b-USt for Regelbesteuert — neutralizes (tax owed = input tax)."""
        # Set Regelbesteuert status
        settings = seeded_session.query(SiteSettings).first()
        settings.is_small_business = False
        seeded_session.flush()

        # Create RC expense with input tax
        _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [
                (Decimal("241.66"), 3125, TaxRule.REVERSE_CHARGE_EU_WITH_INPUT_TAX),  # RC with VSt
            ],
            receipt_type=ReceiptType.EXPENSE,
            counterparty="Etsy Ireland UC",
            receipt_date="2026-01-15",
        )
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/dashboard/euer-summary",
            params={"period_start": "2026-01-01", "period_end": "2026-01-31"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()

        # RC tax = RC input tax (neutralizes)
        assert Decimal(data["rc_tax_owed"]) == Decimal("45.92")
        assert Decimal(data["rc_input_tax"]) == Decimal("45.92")
        assert data["is_small_business"] is False

        # Profit impact: -241.66 (expense) - 45.92 + 45.92 = -241.66 (neutral)
        assert Decimal(data["profit"]) == Decimal("-241.66")

    def should_filter_by_date_range(self, api_client, seeded_session, example_user) -> None:
        """Date range filtering works correctly."""
        # January receipt
        _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [(Decimal("100.00"), 8400, TaxRule.TAX_INCLUDED)],
            receipt_type=ReceiptType.REVENUE,
            receipt_date="2026-01-15",
        )
        # February receipt
        _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [(Decimal("200.00"), 8400, TaxRule.TAX_INCLUDED)],
            receipt_type=ReceiptType.REVENUE,
            receipt_date="2026-02-15",
        )
        seeded_session.commit()

        # Query January only
        response = api_client.get(
            "/api/v1/dashboard/euer-summary",
            params={"period_start": "2026-01-01", "period_end": "2026-01-31"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        # Only January revenue
        assert Decimal(data["revenue_total"]) == Decimal("100.00")
        assert data["period_label"] == "Januar 2026"

    def should_generate_period_label(self, api_client) -> None:
        """Period label generation for various ranges."""
        # Single month
        response = api_client.get(
            "/api/v1/dashboard/euer-summary",
            params={"period_start": "2026-03-01", "period_end": "2026-03-31"},
            headers=AUTH_HEADERS,
        )
        assert response.json()["period_label"] == "März 2026"

        # Multi-month same year
        response = api_client.get(
            "/api/v1/dashboard/euer-summary",
            params={"period_start": "2026-01-01", "period_end": "2026-06-30"},
            headers=AUTH_HEADERS,
        )
        assert response.json()["period_label"] == "Januar – Juni 2026"

    def should_exclude_deleted_receipts(self, api_client, seeded_session, example_user) -> None:
        """Soft-deleted receipts excluded from EÜR."""
        from datetime import datetime, timezone

        # Create and soft-delete a receipt
        receipt = _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [(Decimal("100.00"), 8400, TaxRule.TAX_INCLUDED)],
            receipt_type=ReceiptType.REVENUE,
            receipt_date="2026-01-15",
        )
        receipt.deleted_at = datetime.now(timezone.utc)
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/dashboard/euer-summary",
            params={"period_start": "2026-01-01", "period_end": "2026-01-31"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        # Deleted receipt excluded
        assert Decimal(data["revenue_total"]) == Decimal("0.00")


class TestEuerProfitCalculation:
    """Tests for EÜR profit calculation with various scenarios."""

    def should_calculate_correct_profit_for_etsy_kleinunternehmer(self, api_client, seeded_session, example_user) -> None:
        """January 2026 Etsy scenario: 603.79€ revenue - 241.66€ fees - 45.92€ RC = 316.21€.

        But wait: plan says "effective Jan profit for Kleinunternehmer: 557,87€"
        Let me recalculate: 603.79 - 241.66 = 362.13 profit before RC
        Then: 362.13 - 45.92 = 316.21

        Actually, the plan number (557.87) is: 603.79 (net revenue) - 45.92 (RC-USt) = 557.87
        This is because fees are already subtracted from the revenue figure.

        For EÜR, we model it as:
        - Revenue: 603.79 (net sales after marketplace fees were deducted at source)
        - But if we're tracking fees separately:
          - Revenue: 845.45 (gross sales)
          - Expenses: 241.66 (fees)
          - RC tax: 45.92
          - Profit = 845.45 - 241.66 - 45.92 = 557.87
        """
        # Set Kleinunternehmer
        settings = seeded_session.query(SiteSettings).first()
        settings.is_small_business = True
        seeded_session.flush()

        # Revenue receipt (Etsy sales, gross before fees)
        _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [(Decimal("845.45"), 8195, TaxRule.NO_TAX)],  # Kleinunternehmer revenue
            receipt_type=ReceiptType.REVENUE,
            receipt_date="2026-01-15",
        )

        # Expense receipt (Etsy fees with RC)
        _create_receipt_with_items(
            seeded_session,
            example_user.id,
            [(Decimal("241.66"), 3165, TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX)],
            receipt_type=ReceiptType.EXPENSE,
            counterparty="Etsy Ireland UC",
            receipt_date="2026-01-31",
        )
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/dashboard/euer-summary",
            params={"period_start": "2026-01-01", "period_end": "2026-01-31"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()

        assert Decimal(data["revenue_total"]) == Decimal("845.45")
        assert Decimal(data["expense_total"]) == Decimal("241.66")
        assert Decimal(data["rc_tax_owed"]) == Decimal("45.92")
        assert Decimal(data["rc_input_tax"]) == Decimal("0.00")

        # Profit = 845.45 - 241.66 - 45.92 = 557.87
        assert Decimal(data["profit"]) == Decimal("557.87")
