"""Tests for the receipt matching service."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.receipt import Receipt, ReceiptType
from app.models.receipt_line_item import ReceiptLineItem
from app.models.transaction import Transaction
from app.services.receipt_matching import (
    DATE_TOLERANCE_DAYS,
    suggest_matches_for_receipt,
    suggest_receipts_for_payment,
)

from tests.conftest import TEST_SOURCE_CONFIG_ID, _ensure_test_source_config


def _create_receipt(
    session,
    *,
    user_id: str = "test-user-id",
    receipt_date: date = date(2026, 1, 15),
    amount: Decimal = Decimal("100.00"),
    counterparty: str = "Test Counterparty",
    receipt_number: str = "INV-001",
) -> Receipt:
    """Create a receipt with line item for testing.

    Amount is stored as a line item.
    """
    receipt = Receipt(
        id=str(uuid4()),
        user_id=user_id,
        type=ReceiptType.REVENUE,
        receipt_number=receipt_number,
        date=receipt_date,
        counterparty=counterparty,
    )
    session.add(receipt)
    session.flush()

    # Create line item with the amount
    line_item = ReceiptLineItem(
        id=str(uuid4()),
        receipt_id=receipt.id,
        position=0,
        description="Test item",
        amount=amount,
    )
    session.add(line_item)
    session.flush()

    return receipt


def _create_transaction(
    session,
    *,
    user_id: str = "test-user-id",
    transaction_date: date = date(2026, 1, 15),
    amount: Decimal = Decimal("100.00"),
    counterparty: str = "Test Counterparty",
) -> Transaction:
    """Create a transaction for testing."""
    _ensure_test_source_config(session)
    transaction = Transaction(
        id=str(uuid4()),
        user_id=user_id,
        date=transaction_date,
        amount=amount,
        counterparty=counterparty,
        description="Test",
        source_config_id=TEST_SOURCE_CONFIG_ID,
    )
    session.add(transaction)
    session.flush()
    return transaction


# 📋 suggest_matches_for_receipt — Find Transactions for a Receipt


def should_find_exact_amount_matches(database_session, example_user):
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("150.00"),
    )
    matching_transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("150.00"),
        counterparty="Exact Match",
    )
    # Different amount - should not match
    _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="No Match",
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 1
    assert suggestions[0].id == matching_transaction.id
    assert "Exact amount match" in suggestions[0].reasons


def should_match_negative_transaction_amounts(database_session, example_user):
    """Transactions may have negative amounts (expenses); compare absolute values."""
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),  # Receipt amount is always positive
    )
    # Transaction with negative amount
    negative_transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("-100.00"),
        counterparty="Negative Amount",
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 1
    assert suggestions[0].id == negative_transaction.id


def should_rank_by_date_proximity(database_session, example_user):
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    # Further date (4 days)
    far_transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 19),
        amount=Decimal("100.00"),
        counterparty="Far",
    )
    # Closer date (1 day)
    close_transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 16),
        amount=Decimal("100.00"),
        counterparty="Close",
    )
    # Same date (0 days)
    same_date_transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Same Date",
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 3
    # Sorted by confidence (descending): same date > close > far
    assert suggestions[0].id == same_date_transaction.id
    assert suggestions[0].confidence == pytest.approx(1.0)  # 0.6 + 0.4
    assert suggestions[1].id == close_transaction.id
    assert suggestions[1].confidence == pytest.approx(0.9)  # 0.6 + 0.3
    assert suggestions[2].id == far_transaction.id
    assert suggestions[2].confidence == pytest.approx(0.7)  # 0.6 + 0.1


def should_not_suggest_matches_outside_date_window(database_session, example_user):
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    # Transaction outside tolerance window
    _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15 + DATE_TOLERANCE_DAYS + 1),
        amount=Decimal("100.00"),
        counterparty="Too Far",
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 0


def should_not_suggest_matches_with_different_amount(database_session, example_user):
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    # Amount outside tolerance (>0.50€ difference)
    _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("99.00"),
        counterparty="Different Amount",
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 0


def should_only_suggest_unlinked_transactions(database_session, example_user):
    from app.models.receipt_transaction_link import ReceiptTransactionLink

    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    other_receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        receipt_number="INV-002",
    )
    # Linked transaction via junction table
    linked = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Linked",
    )
    link = ReceiptTransactionLink(receipt_id=other_receipt.id, transaction_id=linked.id)
    database_session.add(link)
    database_session.flush()

    # Unlinked transaction
    unlinked = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Unlinked",
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 1
    assert suggestions[0].id == unlinked.id


def should_return_empty_for_nonexistent_receipt(database_session, example_user):
    suggestions = suggest_matches_for_receipt(database_session, "nonexistent-id")

    assert suggestions == []


def should_suggest_across_users_in_shared_tenant(database_session, example_user):
    """Shared tenant: all users see all data, matching works across users."""
    from app.models import User

    other_user = User(id="other-user-id", provider_id="other-google", provider_type="google", email="other@test.com", name="Other")
    database_session.add(other_user)
    database_session.flush()

    receipt = _create_receipt(
        database_session,
        user_id="test-user-id",
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    # Other user's transaction — visible in shared tenant
    other_transaction = _create_transaction(
        database_session,
        user_id="other-user-id",
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Other User",
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 1
    assert suggestions[0].id == other_transaction.id


# 📋 suggest_receipts_for_payment — Find Receipts for a Transaction


def should_suggest_receipts_for_payment(database_session, example_user):
    transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    matching_receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Match",
    )
    # Different amount - should not match
    _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("50.00"),
        counterparty="No Match",
        receipt_number="INV-002",
    )

    suggestions = suggest_receipts_for_payment(database_session, transaction.id)

    assert len(suggestions) == 1
    assert suggestions[0].id == matching_receipt.id
    assert suggestions[0].receipt_number == "INV-001"


def should_not_suggest_linked_receipts_for_payment(database_session, example_user):
    from app.models.receipt_transaction_link import ReceiptTransactionLink

    other_transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 10),
        amount=Decimal("100.00"),
        counterparty="Other",
    )
    linked_receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    link = ReceiptTransactionLink(receipt_id=linked_receipt.id, transaction_id=other_transaction.id)
    database_session.add(link)
    database_session.flush()

    transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )

    suggestions = suggest_receipts_for_payment(database_session, transaction.id)

    assert len(suggestions) == 0


def should_return_empty_for_nonexistent_transaction(database_session, example_user):
    suggestions = suggest_receipts_for_payment(database_session, "nonexistent-id")

    assert suggestions == []


def should_rank_receipts_by_date_proximity(database_session, example_user):
    transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    # Far receipt
    far_receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 19),
        amount=Decimal("100.00"),
        counterparty="Far",
        receipt_number="INV-FAR",
    )
    # Same date receipt
    same_date_receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Same",
        receipt_number="INV-SAME",
    )

    suggestions = suggest_receipts_for_payment(database_session, transaction.id)

    assert len(suggestions) == 2
    assert suggestions[0].id == same_date_receipt.id
    assert suggestions[0].confidence > suggestions[1].confidence
    assert suggestions[1].id == far_receipt.id


def should_include_receipt_type_in_suggestions(database_session, example_user):
    transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )

    suggestions = suggest_receipts_for_payment(database_session, transaction.id)

    assert len(suggestions) == 1
    assert suggestions[0].id == receipt.id
    assert suggestions[0].receipt_type == "revenue"


# 📋 Counterparty Matching — Normalization and Scoring


def should_boost_confidence_for_exact_counterparty_match(database_session, example_user):
    """Exact counterparty match (after normalization) adds +0.2 confidence."""
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Acme Corp",
    )
    transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="acme corp",  # Same name, different case
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 1
    assert suggestions[0].id == transaction.id
    # 0.6 (amount) + 0.4 (same date) + 0.2 (counterparty match) = 1.2
    assert suggestions[0].confidence == pytest.approx(1.2)
    assert "Counterparty match" in suggestions[0].reasons


def should_boost_confidence_for_partial_counterparty_match(database_session, example_user):
    """Substring counterparty match adds +0.1 confidence."""
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Acme",
    )
    transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Acme Corporation International",
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 1
    assert suggestions[0].id == transaction.id
    # 0.6 (amount) + 0.4 (same date) + 0.1 (partial match) = 1.1
    assert suggestions[0].confidence == pytest.approx(1.1)
    assert "Counterparty partial match" in suggestions[0].reasons


def should_normalize_german_company_suffixes_for_matching(database_session, example_user):
    """German company suffixes (GmbH, UG, AG, etc.) are stripped for matching."""
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Muster GmbH",
    )
    transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Muster",  # Without GmbH
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 1
    assert suggestions[0].id == transaction.id
    assert "Counterparty match" in suggestions[0].reasons


def should_normalize_whitespace_for_counterparty_matching(database_session, example_user):
    """Multiple whitespace chars are collapsed to single space for matching."""
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Test  Company   Name",  # Extra spaces
    )
    _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="test company name",  # Normalized
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 1
    assert "Counterparty match" in suggestions[0].reasons


# 📋 Amount Tolerance — Fuzzy Matching


def should_match_amounts_within_tolerance(database_session, example_user):
    """Amounts within ±0.50€ tolerance should match with reduced confidence."""
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Receipt Company",  # Different from transaction to isolate amount test
    )
    # 0.30€ difference — within tolerance
    transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.30"),
        counterparty="Transaction Company",  # Different counterparty
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 1
    assert suggestions[0].id == transaction.id
    # 0.4 (amount within tolerance) + 0.4 (same date) + 0 (no counterparty match) = 0.8
    assert suggestions[0].confidence == pytest.approx(0.8)
    assert "Amount within tolerance" in suggestions[0].reasons[0]


def should_match_amounts_at_tolerance_boundary(database_session, example_user):
    """Amounts exactly at ±0.50€ tolerance boundary should still match."""
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Receipt At Boundary",
    )
    _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.50"),  # Exactly 0.50€ difference
        counterparty="Transaction At Boundary",
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 1
    assert "Amount within tolerance" in suggestions[0].reasons[0]


# 📋 Private and Internal Transfer Exclusion


def should_exclude_private_transactions_from_suggestions(database_session, example_user):
    """Transactions marked as private should not be suggested."""
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    # Private transaction
    private_transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    private_transaction.is_private = True
    database_session.flush()

    # Non-private transaction
    normal_transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 16),
        amount=Decimal("100.00"),
        counterparty="Normal",
    )

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 1
    assert suggestions[0].id == normal_transaction.id


def should_exclude_internal_transfer_transactions_from_suggestions(database_session, example_user):
    """Transactions marked as internal transfer should not be suggested."""
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    # Internal transfer
    transfer = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    transfer.is_internal_transfer = True
    database_session.flush()

    suggestions = suggest_matches_for_receipt(database_session, receipt.id)

    assert len(suggestions) == 0


# 📋 Filter Parameters


def should_filter_suggestions_by_source_config(database_session, example_user):
    """source_config_id filter limits suggestions to specific bank account."""
    from app.models.source import SourceType, TransactionSourceConfig

    # Create second source config
    other_source = TransactionSourceConfig(
        id="other-source-id",
        user_id=None,
        name="Other Bank",
        type=SourceType.CSV_PARSER,
        check_account_id=1201,
    )
    database_session.add(other_source)
    database_session.flush()

    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )

    # Transaction with default source
    _ensure_test_source_config(database_session)
    _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Default Bank",
    )

    # Transaction with other source
    other_transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Other Bank",
    )
    other_transaction.source_config_id = "other-source-id"
    database_session.flush()

    # Without filter: both match
    all_suggestions = suggest_matches_for_receipt(database_session, receipt.id)
    assert len(all_suggestions) == 2

    # With filter: only one matches
    filtered = suggest_matches_for_receipt(
        database_session,
        receipt.id,
        source_config_id="other-source-id",
    )
    assert len(filtered) == 1
    assert filtered[0].id == other_transaction.id


def should_filter_suggestions_by_counterparty_search(database_session, example_user):
    """search filter limits suggestions by counterparty text (case-insensitive)."""
    receipt = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    # Matching counterparty
    matching = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Amazon Payments",
    )
    # Non-matching counterparty
    _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 16),
        amount=Decimal("100.00"),
        counterparty="PayPal Europe",
    )

    filtered = suggest_matches_for_receipt(
        database_session,
        receipt.id,
        search="amazon",  # Case-insensitive search
    )

    assert len(filtered) == 1
    assert filtered[0].id == matching.id


def should_filter_receipt_suggestions_by_type(database_session, example_user):
    """receipt_type filter limits receipt suggestions by type (revenue/expense)."""
    from app.models.receipt import ReceiptType

    transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )

    # Revenue receipt
    _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Revenue",
    )

    # Expense receipt (need to create manually since helper defaults to revenue)
    expense = Receipt(
        id="expense-receipt-id",
        user_id="test-user-id",
        type=ReceiptType.EXPENSE,
        receipt_number="EXP-001",
        date=date(2026, 1, 15),
        counterparty="Expense",
    )
    database_session.add(expense)
    database_session.flush()

    from app.models.receipt_line_item import ReceiptLineItem

    expense_item = ReceiptLineItem(
        id="expense-item-id",
        receipt_id="expense-receipt-id",
        position=0,
        description="Expense item",
        amount=Decimal("100.00"),
    )
    database_session.add(expense_item)
    database_session.flush()

    # Without filter: both match
    all_suggestions = suggest_receipts_for_payment(database_session, transaction.id)
    assert len(all_suggestions) == 2

    # Filter by expense only
    expense_only = suggest_receipts_for_payment(
        database_session,
        transaction.id,
        receipt_type="expense",
    )
    assert len(expense_only) == 1
    assert expense_only[0].id == expense.id


def should_filter_receipt_suggestions_by_search(database_session, example_user):
    """search filter limits receipt suggestions by counterparty text."""
    transaction = _create_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    # Matching receipt
    matching = _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Amazon Seller Central",
    )
    # Non-matching receipt
    _create_receipt(
        database_session,
        receipt_date=date(2026, 1, 16),
        amount=Decimal("100.00"),
        counterparty="Etsy Payments",
        receipt_number="INV-002",
    )

    filtered = suggest_receipts_for_payment(
        database_session,
        transaction.id,
        search="Amazon",
    )

    assert len(filtered) == 1
    assert filtered[0].id == matching.id
