"""Tests for category suggestion service and endpoint."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.models.accounting_pattern import AccountingPattern
from app.models.receipt import Receipt, ReceiptStatus, ReceiptType
from app.models.receipt_line_item import ReceiptLineItem
from app.services.category_suggestion import learn_from_receipt, suggest_for_counterparty
from sqlalchemy import select

from tests.conftest import AUTH_HEADERS

# Use real SKR03 account IDs from seed data
AMAZON_FEES = 4762  # Amazon Gebühren
SHIPPING = 4730  # Ausgangsfrachten / Versandkosten
INSURANCE = 4750  # Transportversicherung


def _get_pattern(session, counterparty: str) -> AccountingPattern | None:
    """Helper to load the full pattern for assertions on confidence/hits."""
    return session.scalars(
        select(AccountingPattern).where(
            AccountingPattern.pattern == counterparty,
        )
    ).first()


# --- Unit Tests: suggest_for_counterparty ---


def should_return_none_when_no_patterns(seeded_session, example_user):
    result = suggest_for_counterparty(seeded_session, "Unknown Vendor")
    assert result is None


def should_match_exact_counterparty(seeded_session, example_user):
    pattern = AccountingPattern(
        user_id="test-user-id",
        pattern="Amazon DE",
        skr03_account_id=AMAZON_FEES,
        confidence=0.8,
        hits=5,
    )
    seeded_session.add(pattern)
    seeded_session.flush()

    result = suggest_for_counterparty(seeded_session, "Amazon DE")
    assert result == AMAZON_FEES


def should_match_case_insensitive(seeded_session, example_user):
    pattern = AccountingPattern(
        user_id="test-user-id",
        pattern="Hetzner Online",
        skr03_account_id=SHIPPING,
        confidence=0.7,
        hits=3,
    )
    seeded_session.add(pattern)
    seeded_session.flush()

    result = suggest_for_counterparty(seeded_session, "hetzner online")
    assert result == SHIPPING


def should_return_highest_confidence_pattern(seeded_session, example_user):
    low_confidence = AccountingPattern(
        user_id="test-user-id",
        pattern="Amazon",
        skr03_account_id=AMAZON_FEES,
        confidence=0.3,
        hits=1,
    )
    high_confidence = AccountingPattern(
        user_id="test-user-id",
        pattern="Amazon DE",
        skr03_account_id=INSURANCE,
        confidence=0.9,
        hits=10,
    )
    seeded_session.add_all([low_confidence, high_confidence])
    seeded_session.flush()

    result = suggest_for_counterparty(seeded_session, "Amazon")
    assert result == INSURANCE


def should_return_patterns_across_users_in_shared_tenant(seeded_session, example_user):
    """Shared tenant: patterns from any user are visible to all."""
    from app.models import User

    other_user = User(
        id="other-user-id",
        provider_id="other-google-id",
        provider_type="google",
        email="other@example.com",
        name="Other User",
    )
    seeded_session.add(other_user)
    seeded_session.flush()

    pattern = AccountingPattern(
        user_id="other-user-id",
        pattern="Secret Vendor",
        skr03_account_id=AMAZON_FEES,
        confidence=1.0,
        hits=100,
    )
    seeded_session.add(pattern)
    seeded_session.flush()

    result = suggest_for_counterparty(seeded_session, "Secret Vendor")
    assert result == AMAZON_FEES


# --- Unit Tests: learn_from_receipt ---


def _create_receipt_with_line_items(
    session,
    *,
    user_id: str = "test-user-id",
    counterparty: str = "Test Vendor",
    receipt_type: ReceiptType = ReceiptType.EXPENSE,
    line_items: list[dict] | None = None,
) -> Receipt:
    """Helper to create receipt with line items for testing."""
    receipt = Receipt(
        id=str(uuid4()),
        user_id=user_id,
        type=receipt_type,
        receipt_number=f"RE-{uuid4().hex[:6]}",
        date=date(2026, 1, 15),
        counterparty=counterparty,
        status=ReceiptStatus.FINAL,
    )
    session.add(receipt)
    session.flush()

    items = line_items or [{"amount": Decimal("100.00"), "skr03_account_id": AMAZON_FEES}]
    for index, item_data in enumerate(items):
        line_item = ReceiptLineItem(
            receipt_id=receipt.id,
            position=index,
            description="",
            amount=item_data["amount"],
            skr03_account_id=item_data.get("skr03_account_id"),
        )
        session.add(line_item)

    session.flush()
    session.refresh(receipt)
    return receipt


def should_create_new_pattern(seeded_session, example_user):
    receipt = _create_receipt_with_line_items(
        seeded_session,
        counterparty="New Vendor",
        line_items=[{"amount": Decimal("50.00"), "skr03_account_id": SHIPPING}],
    )

    learn_from_receipt(seeded_session, receipt)
    seeded_session.flush()

    assert suggest_for_counterparty(seeded_session, "New Vendor") == SHIPPING

    pattern = _get_pattern(seeded_session, "New Vendor")
    assert pattern is not None
    assert pattern.confidence == 0.5
    assert pattern.hits == 1


def should_increment_hits_for_same_account(seeded_session, example_user):
    receipt1 = _create_receipt_with_line_items(
        seeded_session,
        counterparty="Recurring Vendor",
        line_items=[{"amount": Decimal("50.00"), "skr03_account_id": AMAZON_FEES}],
    )
    learn_from_receipt(seeded_session, receipt1)
    seeded_session.flush()

    receipt2 = _create_receipt_with_line_items(
        seeded_session,
        counterparty="Recurring Vendor",
        line_items=[{"amount": Decimal("75.00"), "skr03_account_id": AMAZON_FEES}],
    )
    learn_from_receipt(seeded_session, receipt2)
    seeded_session.flush()

    assert suggest_for_counterparty(seeded_session, "Recurring Vendor") == AMAZON_FEES

    pattern = _get_pattern(seeded_session, "Recurring Vendor")
    assert pattern is not None
    assert pattern.hits == 2
    assert pattern.confidence == 0.6  # 0.5 + 0.1


def should_reset_confidence_on_account_change(seeded_session, example_user):
    receipt1 = _create_receipt_with_line_items(
        seeded_session,
        counterparty="Changing Vendor",
        line_items=[{"amount": Decimal("50.00"), "skr03_account_id": AMAZON_FEES}],
    )
    learn_from_receipt(seeded_session, receipt1)
    seeded_session.flush()

    # Reinforce 3 times
    for _ in range(3):
        receipt = _create_receipt_with_line_items(
            seeded_session,
            counterparty="Changing Vendor",
            line_items=[{"amount": Decimal("50.00"), "skr03_account_id": AMAZON_FEES}],
        )
        learn_from_receipt(seeded_session, receipt)
        seeded_session.flush()

    pattern = _get_pattern(seeded_session, "Changing Vendor")
    assert pattern is not None
    assert pattern.hits == 4
    assert round(pattern.confidence, 1) == 0.8  # 0.5 + 0.3 (float precision)

    # Now change account
    receipt_new = _create_receipt_with_line_items(
        seeded_session,
        counterparty="Changing Vendor",
        line_items=[{"amount": Decimal("50.00"), "skr03_account_id": SHIPPING}],
    )
    learn_from_receipt(seeded_session, receipt_new)
    seeded_session.flush()

    assert suggest_for_counterparty(seeded_session, "Changing Vendor") == SHIPPING

    pattern = _get_pattern(seeded_session, "Changing Vendor")
    assert pattern is not None
    assert pattern.confidence == 0.5
    assert pattern.hits == 1


def should_skip_line_items_without_account(seeded_session, example_user):
    receipt = _create_receipt_with_line_items(
        seeded_session,
        counterparty="No Account Vendor",
        line_items=[{"amount": Decimal("50.00"), "skr03_account_id": None}],
    )

    learn_from_receipt(seeded_session, receipt)
    seeded_session.flush()

    assert suggest_for_counterparty(seeded_session, "No Account Vendor") is None


def should_skip_empty_counterparty(seeded_session, example_user):
    receipt = _create_receipt_with_line_items(
        seeded_session,
        counterparty="",
        line_items=[{"amount": Decimal("50.00"), "skr03_account_id": AMAZON_FEES}],
    )

    learn_from_receipt(seeded_session, receipt)
    seeded_session.flush()

    from sqlalchemy import func

    count = seeded_session.scalar(select(func.count()).select_from(AccountingPattern).where(AccountingPattern.pattern == ""))
    assert count == 0


# --- Integration Tests: Suggestion Endpoint ---


def should_return_suggestion_via_api(api_client, database_session):
    pattern = AccountingPattern(
        user_id="test-user-id",
        pattern="Hetzner Online GmbH",
        skr03_account_id=SHIPPING,
        confidence=0.8,
        hits=5,
    )
    database_session.add(pattern)
    database_session.flush()

    response = api_client.get(
        "/api/v1/receipts/suggest-account",
        params={"counterparty": "Hetzner Online GmbH"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["skr03_account_id"] == SHIPPING
    assert data["confidence"] == 0.8
    assert data["pattern"] == "Hetzner Online GmbH"


def should_return_404_when_no_suggestion(api_client):
    response = api_client.get(
        "/api/v1/receipts/suggest-account",
        params={"counterparty": "Unknown Vendor XYZ"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 404


def should_require_counterparty_parameter(api_client):
    response = api_client.get(
        "/api/v1/receipts/suggest-account",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 422
