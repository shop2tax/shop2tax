"""Tests for auto-linking transactions to receipts by oms_order_id."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.receipt import Receipt, ReceiptType
from app.models.receipt_transaction_link import ReceiptTransactionLink
from app.models.source import SourceType, TransactionSourceConfig
from app.models.transaction import Transaction
from app.services.receipt_service import auto_link_by_oms_order_id, link_receipt_to_payment

USER_ID = "test-user-id"


@pytest.fixture
def source_config_id(seeded_session, example_user):
    """A transaction source config (check_account_id auto-assigned by conftest event)."""
    config = TransactionSourceConfig(
        id=str(uuid4()),
        user_id=None,
        name="Auto-Link Test Etsy",
        type=SourceType.CSV_PARSER,
    )
    seeded_session.add(config)
    seeded_session.flush()
    return config.id


def _make_receipt(session, *, oms_order_id: str, locked: bool = False) -> Receipt:
    receipt = Receipt(
        user_id=USER_ID,
        type=ReceiptType.REVENUE,
        receipt_number=f"R-{oms_order_id}",
        date=date(2026, 1, 15),
        counterparty="Customer",
        oms_order_id=oms_order_id,
    )
    if locked:
        receipt.locked_at = datetime.now(UTC)
    session.add(receipt)
    session.flush()
    return receipt


def _make_transaction(
    session,
    source_config_id: str,
    *,
    oms_order_id: str | None = "ORDER-1",
    category: str = "revenue",
    deleted: bool = False,
) -> Transaction:
    transaction = Transaction(
        id=str(uuid4()),
        user_id=USER_ID,
        date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Customer",
        description="Sale",
        source_config_id=source_config_id,
        oms_order_id=oms_order_id,
        extra_data={"marketplace_category": category},
    )
    if deleted:
        transaction.deleted_at = datetime.now(UTC)
    session.add(transaction)
    session.flush()
    return transaction


def _link_count(session, receipt_id: str, transaction_id: str) -> int:
    return len(
        session.execute(
            ReceiptTransactionLink.__table__.select().where(
                ReceiptTransactionLink.receipt_id == receipt_id,
                ReceiptTransactionLink.transaction_id == transaction_id,
            )
        ).all()
    )


def should_link_revenue_transaction_to_receipt_by_oms_order_id(seeded_session, example_user, source_config_id):
    receipt = _make_receipt(seeded_session, oms_order_id="ORDER-1")
    transaction = _make_transaction(seeded_session, source_config_id, oms_order_id="ORDER-1")

    result = auto_link_by_oms_order_id(seeded_session, USER_ID)

    assert result.linked == 1
    assert result.already_linked == 0
    assert result.no_receipt == 0
    assert result.skipped_locked == 0
    assert _link_count(seeded_session, receipt.id, transaction.id) == 1


def should_not_link_fee_transaction(seeded_session, example_user, source_config_id):
    _make_receipt(seeded_session, oms_order_id="ORDER-1")
    _make_transaction(seeded_session, source_config_id, oms_order_id="ORDER-1", category="fee")

    result = auto_link_by_oms_order_id(seeded_session, USER_ID)

    assert result.linked == 0
    assert result.no_receipt == 0


def should_not_link_transfer_transaction(seeded_session, example_user, source_config_id):
    _make_receipt(seeded_session, oms_order_id="ORDER-1")
    _make_transaction(seeded_session, source_config_id, oms_order_id="ORDER-1", category="transfer")

    result = auto_link_by_oms_order_id(seeded_session, USER_ID)

    assert result.linked == 0


def should_skip_already_linked_transaction(seeded_session, example_user, source_config_id):
    receipt = _make_receipt(seeded_session, oms_order_id="ORDER-1")
    transaction = _make_transaction(seeded_session, source_config_id, oms_order_id="ORDER-1")
    link_receipt_to_payment(seeded_session, receipt.id, transaction.id, USER_ID)

    result = auto_link_by_oms_order_id(seeded_session, USER_ID)

    assert result.linked == 0
    assert result.already_linked == 1
    assert _link_count(seeded_session, receipt.id, transaction.id) == 1


def should_skip_locked_receipt_gracefully(seeded_session, example_user, source_config_id):
    receipt = _make_receipt(seeded_session, oms_order_id="ORDER-1", locked=True)
    transaction = _make_transaction(seeded_session, source_config_id, oms_order_id="ORDER-1")

    result = auto_link_by_oms_order_id(seeded_session, USER_ID)

    assert result.linked == 0
    assert result.skipped_locked == 1
    assert _link_count(seeded_session, receipt.id, transaction.id) == 0


def should_return_no_receipt_when_receipt_missing(seeded_session, example_user, source_config_id):
    _make_transaction(seeded_session, source_config_id, oms_order_id="ORDER-NOPE")

    result = auto_link_by_oms_order_id(seeded_session, USER_ID)

    assert result.linked == 0
    assert result.no_receipt == 1


def should_ignore_deleted_transactions(seeded_session, example_user, source_config_id):
    _make_receipt(seeded_session, oms_order_id="ORDER-1")
    _make_transaction(seeded_session, source_config_id, oms_order_id="ORDER-1", deleted=True)

    result = auto_link_by_oms_order_id(seeded_session, USER_ID)

    assert result.linked == 0
    assert result.no_receipt == 0


def should_persist_oms_order_id_on_import(api_client, database_session):
    config = TransactionSourceConfig(
        id=str(uuid4()),
        user_id=None,
        name="Import Test Etsy",
        type=SourceType.CSV_PARSER,
    )
    database_session.add(config)
    database_session.flush()

    payload = {
        "source_config_id": config.id,
        "items": [
            {
                "date": "2026-01-15",
                "amount": "100.00",
                "counterparty": "Customer",
                "description": "Sale",
                "oms_order_id": "ORDER-42",
                "extra_data": {"marketplace_category": "revenue", "oms_order_id": "ORDER-42"},
            }
        ],
    }
    response = api_client.post(
        "/api/v1/transactions/import",
        json=payload,
        headers={
            "x-user-id": USER_ID,
            "x-user-name": "Test User",
            "x-user-email": "test@example.com",
        },
    )
    assert response.status_code == 201

    transaction = database_session.execute(Transaction.__table__.select().where(Transaction.oms_order_id == "ORDER-42")).first()
    assert transaction is not None
    assert transaction.oms_order_id == "ORDER-42"
    # oms_order_id is stripped from extra_data (dedicated column)
    assert "oms_order_id" not in (transaction.extra_data or {})
