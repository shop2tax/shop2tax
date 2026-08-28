"""Tests for Payout↔Bank-Matching endpoints."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.models.source import SourceType, TransactionSourceConfig
from app.models.transaction import Transaction

from tests.conftest import AUTH_HEADERS

# Relative to today — the endpoint only searches the last `days_back` (default 30) days.
_BASE_DATE = date.today() - timedelta(days=7)
_BASE_DATE_PLUS_2 = _BASE_DATE + timedelta(days=2)


def _create_source_config(
    session,
    *,
    name: str,
    source_type: SourceType,
    check_account_id: int,
) -> TransactionSourceConfig:
    """Create a TransactionSourceConfig for testing."""
    config = TransactionSourceConfig(
        id=str(uuid4()),
        user_id=None,
        name=name,
        type=source_type,
        check_account_id=check_account_id,
    )
    session.add(config)
    session.flush()
    return config


def _create_transaction(
    session,
    *,
    user_id: str = "test-user-id",
    source_config_id: str,
    amount: Decimal,
    counterparty: str = "Test",
    description: str = "Test",
    transaction_date: date = _BASE_DATE,
    is_internal_transfer: bool = False,
) -> Transaction:
    """Create a transaction for testing."""
    transaction = Transaction(
        id=str(uuid4()),
        user_id=user_id,
        date=transaction_date,
        amount=amount,
        counterparty=counterparty,
        description=description,
        source_config_id=source_config_id,
        is_internal_transfer=is_internal_transfer,
    )
    session.add(transaction)
    session.flush()
    return transaction


class TestPayoutSuggestions:
    """Tests for GET /api/v1/transactions/payout-suggestions."""

    def should_return_empty_when_no_deposits(self, api_client) -> None:
        """No bank deposits → empty response."""
        response = api_client.get(
            "/api/v1/transactions/payout-suggestions",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deposit_count"] == 0
        assert data["deposits"] == []

    def should_match_bank_deposit_to_marketplace_payout(self, api_client, seeded_session, example_user) -> None:
        """Bank deposit matches marketplace payout by amount."""
        bank_source = _create_source_config(
            seeded_session,
            name="DKB",
            source_type=SourceType.CSV_MAPPING,
            check_account_id=1200,
        )
        etsy_source = _create_source_config(
            seeded_session,
            name="Etsy",
            source_type=SourceType.MARKETPLACE_MAPPING,
            check_account_id=1201,
        )

        # Bank deposit (positive = inflow)
        _create_transaction(
            seeded_session,
            source_config_id=bank_source.id,
            amount=Decimal("195.32"),
            counterparty="ETSY IRELAND UNLIMITED COMPANY",
            description="Gutschrift Etsy",
            transaction_date=_BASE_DATE_PLUS_2,
        )
        # Marketplace payout (negative = outflow from clearing account)
        _create_transaction(
            seeded_session,
            source_config_id=etsy_source.id,
            amount=Decimal("-195.32"),
            counterparty="Etsy Payout",
            description="Payout Jan 2026",
            transaction_date=_BASE_DATE,
            is_internal_transfer=True,
        )
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/transactions/payout-suggestions",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deposit_count"] == 1
        assert len(data["deposits"]) == 1

        deposit = data["deposits"][0]
        assert Decimal(deposit["bank_amount"]) == Decimal("195.32")
        assert len(deposit["suggestions"]) == 1

        suggestion = deposit["suggestions"][0]
        assert Decimal(suggestion["payout_amount"]) == Decimal("-195.32")
        assert suggestion["payout_source_name"] == "Etsy"
        assert suggestion["match_score"] > 0.5  # Date within 3 days → score boost

    def should_not_match_when_amount_differs_more_than_threshold(self, api_client, seeded_session, example_user) -> None:
        """Amount difference > 0.02€ → no suggestion."""
        bank_source = _create_source_config(
            seeded_session,
            name="DKB",
            source_type=SourceType.CSV_MAPPING,
            check_account_id=1200,
        )
        etsy_source = _create_source_config(
            seeded_session,
            name="Etsy",
            source_type=SourceType.MARKETPLACE_MAPPING,
            check_account_id=1201,
        )

        _create_transaction(
            seeded_session,
            source_config_id=bank_source.id,
            amount=Decimal("195.32"),
            counterparty="ETSY IRELAND",
            transaction_date=_BASE_DATE_PLUS_2,
        )
        _create_transaction(
            seeded_session,
            source_config_id=etsy_source.id,
            amount=Decimal("-195.40"),  # 0.08€ difference — too much
            counterparty="Etsy Payout",
            transaction_date=_BASE_DATE,
            is_internal_transfer=True,
        )
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/transactions/payout-suggestions",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deposit_count"] == 0

    def should_allow_tiny_amount_difference(self, api_client, seeded_session, example_user) -> None:
        """Amount difference ≤ 0.02€ → still matches (rounding tolerance)."""
        bank_source = _create_source_config(
            seeded_session,
            name="Finom",
            source_type=SourceType.CSV_MAPPING,
            check_account_id=1200,
        )
        etsy_source = _create_source_config(
            seeded_session,
            name="Etsy",
            source_type=SourceType.MARKETPLACE_MAPPING,
            check_account_id=1201,
        )

        _create_transaction(
            seeded_session,
            source_config_id=bank_source.id,
            amount=Decimal("195.33"),  # 0.01€ off
            counterparty="ETSY IRELAND",
            transaction_date=_BASE_DATE,
        )
        _create_transaction(
            seeded_session,
            source_config_id=etsy_source.id,
            amount=Decimal("-195.32"),
            counterparty="Etsy Payout",
            transaction_date=_BASE_DATE,
            is_internal_transfer=True,
        )
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/transactions/payout-suggestions",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deposit_count"] == 1
        assert len(data["deposits"][0]["suggestions"]) == 1

    def should_exclude_already_linked_transactions(self, api_client, seeded_session, example_user) -> None:
        """Already-linked transactions are excluded from suggestions."""
        bank_source = _create_source_config(
            seeded_session,
            name="DKB",
            source_type=SourceType.CSV_MAPPING,
            check_account_id=1200,
        )
        etsy_source = _create_source_config(
            seeded_session,
            name="Etsy",
            source_type=SourceType.MARKETPLACE_MAPPING,
            check_account_id=1201,
        )

        bank_tx = _create_transaction(
            seeded_session,
            source_config_id=bank_source.id,
            amount=Decimal("195.32"),
            counterparty="ETSY IRELAND",
            transaction_date=_BASE_DATE_PLUS_2,
        )
        payout_tx = _create_transaction(
            seeded_session,
            source_config_id=etsy_source.id,
            amount=Decimal("-195.32"),
            counterparty="Etsy Payout",
            transaction_date=_BASE_DATE,
            is_internal_transfer=True,
        )

        # Pre-link them
        bank_tx.linked_transfer_id = payout_tx.id
        bank_tx.is_internal_transfer = True
        payout_tx.linked_transfer_id = bank_tx.id
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/transactions/payout-suggestions",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deposit_count"] == 0

    def should_boost_score_for_same_day_match(self, api_client, seeded_session, example_user) -> None:
        """Same date → highest score, farther dates → lower score."""
        bank_source = _create_source_config(
            seeded_session,
            name="DKB",
            source_type=SourceType.CSV_MAPPING,
            check_account_id=1200,
        )
        etsy_source = _create_source_config(
            seeded_session,
            name="Etsy",
            source_type=SourceType.MARKETPLACE_MAPPING,
            check_account_id=1201,
        )

        _create_transaction(
            seeded_session,
            source_config_id=bank_source.id,
            amount=Decimal("100.00"),
            counterparty="ETSY IRELAND",
            transaction_date=_BASE_DATE,
        )
        # Same date payout
        _create_transaction(
            seeded_session,
            source_config_id=etsy_source.id,
            amount=Decimal("-100.00"),
            counterparty="Etsy Payout Same Day",
            transaction_date=_BASE_DATE,
            is_internal_transfer=True,
        )
        seeded_session.commit()

        response = api_client.get(
            "/api/v1/transactions/payout-suggestions",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        suggestion = data["deposits"][0]["suggestions"][0]
        # Same date: 0.5 base + 0.5 date boost = 1.0
        assert suggestion["match_score"] == 1.0


class TestConfirmPayoutMatch:
    """Tests for POST /api/v1/transactions/confirm-payout-match."""

    def should_link_bank_deposit_to_payout(self, api_client, seeded_session, example_user) -> None:
        """Confirming a match creates bidirectional linked_transfer."""
        bank_source = _create_source_config(
            seeded_session,
            name="DKB",
            source_type=SourceType.CSV_MAPPING,
            check_account_id=1200,
        )
        etsy_source = _create_source_config(
            seeded_session,
            name="Etsy",
            source_type=SourceType.MARKETPLACE_MAPPING,
            check_account_id=1201,
        )

        bank_tx = _create_transaction(
            seeded_session,
            source_config_id=bank_source.id,
            amount=Decimal("195.32"),
            counterparty="ETSY IRELAND",
            transaction_date=_BASE_DATE_PLUS_2,
        )
        payout_tx = _create_transaction(
            seeded_session,
            source_config_id=etsy_source.id,
            amount=Decimal("-195.32"),
            counterparty="Etsy Payout",
            transaction_date=_BASE_DATE,
            is_internal_transfer=True,
        )
        seeded_session.commit()

        response = api_client.post(
            "/api/v1/transactions/confirm-payout-match",
            json={
                "bank_transaction_id": bank_tx.id,
                "payout_transaction_id": payout_tx.id,
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["bank_transaction_id"] == bank_tx.id
        assert data["payout_transaction_id"] == payout_tx.id
        assert "Geldtransit" in data["message"]

        # Verify bidirectional link in DB
        seeded_session.expire_all()
        bank_tx_db = seeded_session.get(Transaction, bank_tx.id)
        payout_tx_db = seeded_session.get(Transaction, payout_tx.id)

        assert bank_tx_db.linked_transfer_id == payout_tx.id
        assert bank_tx_db.is_internal_transfer is True
        assert payout_tx_db.linked_transfer_id == bank_tx.id

    def should_reject_already_linked_bank_transaction(self, api_client, seeded_session, example_user) -> None:
        """Bank transaction already linked → 400."""
        bank_source = _create_source_config(
            seeded_session,
            name="DKB",
            source_type=SourceType.CSV_MAPPING,
            check_account_id=1200,
        )
        etsy_source = _create_source_config(
            seeded_session,
            name="Etsy",
            source_type=SourceType.MARKETPLACE_MAPPING,
            check_account_id=1201,
        )

        other_tx = _create_transaction(
            seeded_session,
            source_config_id=etsy_source.id,
            amount=Decimal("-100.00"),
            counterparty="Other",
            is_internal_transfer=True,
        )
        bank_tx = _create_transaction(
            seeded_session,
            source_config_id=bank_source.id,
            amount=Decimal("195.32"),
            counterparty="ETSY IRELAND",
        )
        bank_tx.linked_transfer_id = other_tx.id
        bank_tx.is_internal_transfer = True

        payout_tx = _create_transaction(
            seeded_session,
            source_config_id=etsy_source.id,
            amount=Decimal("-195.32"),
            counterparty="Etsy Payout",
            is_internal_transfer=True,
        )
        seeded_session.commit()

        response = api_client.post(
            "/api/v1/transactions/confirm-payout-match",
            json={
                "bank_transaction_id": bank_tx.id,
                "payout_transaction_id": payout_tx.id,
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 400
        assert "already linked" in response.json()["detail"]

    def should_reject_amount_mismatch(self, api_client, seeded_session, example_user) -> None:
        """Amount difference > 0.02€ → 400."""
        bank_source = _create_source_config(
            seeded_session,
            name="DKB",
            source_type=SourceType.CSV_MAPPING,
            check_account_id=1200,
        )
        etsy_source = _create_source_config(
            seeded_session,
            name="Etsy",
            source_type=SourceType.MARKETPLACE_MAPPING,
            check_account_id=1201,
        )

        bank_tx = _create_transaction(
            seeded_session,
            source_config_id=bank_source.id,
            amount=Decimal("195.32"),
            counterparty="ETSY IRELAND",
        )
        payout_tx = _create_transaction(
            seeded_session,
            source_config_id=etsy_source.id,
            amount=Decimal("-200.00"),  # Too far off
            counterparty="Etsy Payout",
            is_internal_transfer=True,
        )
        seeded_session.commit()

        response = api_client.post(
            "/api/v1/transactions/confirm-payout-match",
            json={
                "bank_transaction_id": bank_tx.id,
                "payout_transaction_id": payout_tx.id,
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 400
        assert "mismatch" in response.json()["detail"].lower()

    def should_reject_non_deposit_bank_transaction(self, api_client, seeded_session, example_user) -> None:
        """Bank transaction with negative amount → 400."""
        bank_source = _create_source_config(
            seeded_session,
            name="DKB",
            source_type=SourceType.CSV_MAPPING,
            check_account_id=1200,
        )
        etsy_source = _create_source_config(
            seeded_session,
            name="Etsy",
            source_type=SourceType.MARKETPLACE_MAPPING,
            check_account_id=1201,
        )

        bank_tx = _create_transaction(
            seeded_session,
            source_config_id=bank_source.id,
            amount=Decimal("-50.00"),  # Negative — not a deposit
            counterparty="Some Payment",
        )
        payout_tx = _create_transaction(
            seeded_session,
            source_config_id=etsy_source.id,
            amount=Decimal("-50.00"),
            counterparty="Etsy Payout",
            is_internal_transfer=True,
        )
        seeded_session.commit()

        response = api_client.post(
            "/api/v1/transactions/confirm-payout-match",
            json={
                "bank_transaction_id": bank_tx.id,
                "payout_transaction_id": payout_tx.id,
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 400
        assert "deposit" in response.json()["detail"].lower()
