"""Integration tests for the receipts router (Beleg-System)."""

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from app.models.receipt import Receipt, ReceiptType
from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog
from app.models.receipt_line_item import ReceiptLineItem

from tests.conftest import AUTH_HEADERS, _create_example_transaction

# Fake PDF content with valid magic bytes (used across file upload tests)
FAKE_PDF_CONTENT = b"%PDF-1.4 fake pdf content for testing"
FAKE_PDF_HASH = hashlib.sha256(FAKE_PDF_CONTENT).hexdigest()


def _create_example_receipt(
    session,
    *,
    user_id: str = "test-user-id",
    receipt_type: ReceiptType = ReceiptType.REVENUE,
    receipt_number: str = "INV-001",
    receipt_date: date = date(2026, 1, 15),
    amount: Decimal = Decimal("100.00"),
    counterparty: str = "Example Customer",
    description: str = "Test receipt",
    oms_order_id: str | None = None,
    skr03_account_id: int | None = None,
    locked_at: datetime | None = None,
) -> Receipt:
    """Create a receipt with a line item in the test database.

    Amount is now stored as a line item, not on the receipt itself.
    """
    receipt = Receipt(
        id=str(uuid4()),
        user_id=user_id,
        type=receipt_type,
        receipt_number=receipt_number,
        date=receipt_date,
        counterparty=counterparty,
        description=description,
        oms_order_id=oms_order_id,
        locked_at=locked_at,
    )
    session.add(receipt)
    session.flush()

    # Create a single line item with the amount
    line_item = ReceiptLineItem(
        id=str(uuid4()),
        receipt_id=receipt.id,
        position=0,
        description=description,
        amount=amount,
        skr03_account_id=skr03_account_id,
    )
    session.add(line_item)
    session.flush()

    return receipt


# 📋 GET /api/v1/receipts — List


def should_list_receipts_empty(api_client):
    response = api_client.get("/api/v1/receipts", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["receipts"] == []
    assert body["total"] == 0


def should_list_receipts_with_results(api_client, database_session):
    _create_example_receipt(database_session, counterparty="Customer A")
    _create_example_receipt(
        database_session,
        counterparty="Customer B",
        receipt_number="INV-002",
        amount=Decimal("50.00"),
    )

    response = api_client.get("/api/v1/receipts", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["receipts"]) == 2


def should_filter_by_receipt_type(api_client, database_session):
    _create_example_receipt(database_session, receipt_type=ReceiptType.REVENUE, counterparty="Revenue Co")
    _create_example_receipt(
        database_session,
        receipt_type=ReceiptType.EXPENSE,
        counterparty="Expense Co",
        receipt_number="EXP-001",
    )

    response = api_client.get("/api/v1/receipts?receipt_type=expense", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["receipts"][0]["type"] == "expense"
    assert body["receipts"][0]["counterparty"] == "Expense Co"


def should_filter_by_date_range(api_client, database_session):
    _create_example_receipt(database_session, receipt_date=date(2026, 1, 10), counterparty="January")
    _create_example_receipt(
        database_session,
        receipt_date=date(2026, 2, 15),
        counterparty="February",
        receipt_number="INV-002",
    )
    _create_example_receipt(
        database_session,
        receipt_date=date(2026, 3, 20),
        counterparty="March",
        receipt_number="INV-003",
    )

    response = api_client.get(
        "/api/v1/receipts?start_date=2026-02-01&end_date=2026-02-28",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["receipts"][0]["counterparty"] == "February"


def should_filter_by_locked_status(api_client, database_session):
    _create_example_receipt(database_session, counterparty="Unlocked")
    _create_example_receipt(
        database_session,
        locked_at=datetime.now(UTC),
        counterparty="Locked",
        receipt_number="INV-002",
    )

    response = api_client.get("/api/v1/receipts?is_locked=true", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["receipts"][0]["counterparty"] == "Locked"
    assert body["receipts"][0]["is_locked"] is True


def should_exclude_soft_deleted_from_list(api_client, database_session):
    deleted_receipt = _create_example_receipt(database_session, counterparty="Deleted")
    deleted_receipt.deleted_at = datetime.now(UTC)
    database_session.flush()

    _create_example_receipt(database_session, counterparty="Active", receipt_number="INV-002")

    response = api_client.get("/api/v1/receipts", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["receipts"][0]["counterparty"] == "Active"


def should_list_all_receipts_in_shared_tenant(api_client, database_session):
    """Shared tenant: all users see all receipts."""
    from app.models import User

    other_user = User(
        id="other-user-id",
        provider_id="google-other",
        provider_type="google",
        email="other@example.com",
        name="Other User",
    )
    database_session.add(other_user)
    database_session.flush()

    _create_example_receipt(database_session, user_id="test-user-id", counterparty="My Receipt")
    _create_example_receipt(
        database_session,
        user_id="other-user-id",
        counterparty="Other Receipt",
        receipt_number="INV-002",
    )

    response = api_client.get("/api/v1/receipts", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2


# 📋 GET /api/v1/receipts/{id} — Get Single


def should_get_receipt_by_id(api_client, database_session):
    receipt = _create_example_receipt(database_session, counterparty="Detail Co", amount=Decimal("42.50"))

    response = api_client.get(f"/api/v1/receipts/{receipt.id}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == receipt.id
    assert body["counterparty"] == "Detail Co"
    assert body["amount"] == "42.50"
    assert body["type"] == "revenue"
    assert body["is_locked"] is False


def should_return_404_for_missing_receipt(api_client):
    response = api_client.get("/api/v1/receipts/nonexistent-id", headers=AUTH_HEADERS)
    assert response.status_code == 404
    assert response.json()["detail"] == "Receipt 'nonexistent-id' not found"


def should_return_404_for_soft_deleted_receipt(api_client, database_session):
    receipt = _create_example_receipt(database_session)
    receipt.deleted_at = datetime.now(UTC)
    database_session.flush()

    response = api_client.get(f"/api/v1/receipts/{receipt.id}", headers=AUTH_HEADERS)
    assert response.status_code == 404


def should_get_any_users_receipt_in_shared_tenant(api_client, database_session):
    """Shared tenant: any user can see any receipt."""
    from app.models import User

    other_user = User(
        id="other-user-id-2",
        provider_id="google-other-2",
        provider_type="google",
        email="other2@example.com",
        name="Other User 2",
    )
    database_session.add(other_user)
    database_session.flush()

    receipt = _create_example_receipt(database_session, user_id="other-user-id-2")

    response = api_client.get(f"/api/v1/receipts/{receipt.id}", headers=AUTH_HEADERS)
    assert response.status_code == 200


# 📋 POST /api/v1/receipts — Create Expense Receipt


def should_create_expense_receipt(api_client):
    response = api_client.post(
        "/api/v1/receipts",
        json={
            "receipt_number": "EXP-001",
            "date": "2026-01-20",
            "counterparty": "Supplier Inc",
            "description": "Office supplies",
            "line_items": [{"amount": "150.00", "description": "Office supplies"}],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["receipt_number"] == "EXP-001"
    assert body["amount"] == "150.00"
    assert body["counterparty"] == "Supplier Inc"
    assert body["type"] == "expense"
    assert body["is_locked"] is False
    assert body["id"] is not None


def should_create_expense_receipt_with_account(api_client):
    response = api_client.post(
        "/api/v1/receipts",
        json={
            "receipt_number": "EXP-002",
            "date": "2026-01-20",
            "counterparty": "Supplier Co",
            "description": "With account",
            "line_items": [
                {
                    "amount": "75.00",
                    "description": "With account",
                    "skr03_account_id": 4761,
                }
            ],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201
    body = response.json()
    # SKR03 account is now on line items, not receipt level
    assert len(body["line_items"]) == 1
    assert body["line_items"][0]["skr03_account_id"] == 4761


def should_reject_missing_line_items(api_client):
    response = api_client.post(
        "/api/v1/receipts",
        json={
            "receipt_number": "EXP-003",
            "date": "2026-01-20",
            "counterparty": "Invalid",
            "line_items": [],  # Empty list should be rejected
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422
    # Pydantic validation error for empty line_items
    detail = response.json()["detail"]
    assert any("line_item" in str(error.get("loc", "")).lower() for error in detail)


def should_create_audit_log_on_receipt_creation(api_client, database_session):
    response = api_client.post(
        "/api/v1/receipts",
        json={
            "receipt_number": "EXP-AUDIT",
            "date": "2026-01-20",
            "counterparty": "Audit Test",
            "line_items": [{"amount": "100.00", "description": "Test"}],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201
    receipt_id = response.json()["id"]

    # Check audit log was created
    from sqlalchemy import select

    audit_log = database_session.execute(select(ReceiptAuditLog).where(ReceiptAuditLog.receipt_id == receipt_id)).scalar_one_or_none()
    assert audit_log is not None
    assert audit_log.action == ReceiptAuditAction.CREATED


# 📋 DELETE /api/v1/receipts/{id} — Soft Delete


def should_soft_delete_unlinked_receipt(api_client, database_session):
    receipt = _create_example_receipt(database_session)

    response = api_client.delete(f"/api/v1/receipts/{receipt.id}", headers=AUTH_HEADERS)
    assert response.status_code == 204

    # Verify it's no longer returned by GET
    get_response = api_client.get(f"/api/v1/receipts/{receipt.id}", headers=AUTH_HEADERS)
    assert get_response.status_code == 404


def should_prevent_delete_of_linked_receipt(api_client, database_session):
    from app.models.receipt_transaction_link import ReceiptTransactionLink

    receipt = _create_example_receipt(database_session)
    transaction = _create_example_transaction(database_session)
    link = ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id)
    database_session.add(link)
    database_session.flush()

    response = api_client.delete(f"/api/v1/receipts/{receipt.id}", headers=AUTH_HEADERS)
    assert response.status_code == 409
    assert "linked to" in response.json()["detail"]
    assert "Unlink first" in response.json()["detail"]


def should_prevent_delete_of_locked_receipt(api_client, database_session):
    receipt = _create_example_receipt(database_session, locked_at=datetime.now(UTC))

    response = api_client.delete(f"/api/v1/receipts/{receipt.id}", headers=AUTH_HEADERS)
    assert response.status_code == 403
    assert "locked" in response.json()["detail"].lower()


def should_create_audit_log_on_delete(api_client, database_session):
    receipt = _create_example_receipt(database_session)
    receipt_id = receipt.id

    response = api_client.delete(f"/api/v1/receipts/{receipt_id}", headers=AUTH_HEADERS)
    assert response.status_code == 204

    # Check audit log
    from sqlalchemy import select

    audit_logs = database_session.execute(select(ReceiptAuditLog).where(ReceiptAuditLog.receipt_id == receipt_id)).scalars().all()
    assert any(log.action == ReceiptAuditAction.DELETED for log in audit_logs)


# 📋 POST /api/v1/receipts/{id}/link — Link Receipt to Payment


def should_link_receipt_to_payment(api_client, database_session):
    from app.models.receipt_transaction_link import ReceiptTransactionLink

    receipt = _create_example_receipt(database_session, amount=Decimal("100.00"))
    transaction = _create_example_transaction(database_session, amount=Decimal("100.00"))

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link",
        json={"transaction_id": transaction.id},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == receipt.id

    # Verify link was created in junction table
    from sqlalchemy import select

    link = database_session.execute(
        select(ReceiptTransactionLink).where(
            ReceiptTransactionLink.receipt_id == receipt.id,
            ReceiptTransactionLink.transaction_id == transaction.id,
        )
    ).scalar_one_or_none()
    assert link is not None


def should_create_audit_log_on_link(api_client, database_session):
    receipt = _create_example_receipt(database_session, amount=Decimal("100.00"))
    transaction = _create_example_transaction(database_session, amount=Decimal("100.00"))

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link",
        json={"transaction_id": transaction.id},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200

    # Check audit log
    from sqlalchemy import select

    audit_logs = database_session.execute(select(ReceiptAuditLog).where(ReceiptAuditLog.receipt_id == receipt.id)).scalars().all()
    assert any(log.action == ReceiptAuditAction.LINKED for log in audit_logs)


def should_reject_link_to_nonexistent_transaction(api_client, database_session):
    receipt = _create_example_receipt(database_session)

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link",
        json={"transaction_id": "00000000-0000-0000-0000-000000000099"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404


def should_reject_link_of_locked_receipt(api_client, database_session):
    receipt = _create_example_receipt(database_session, locked_at=datetime.now(UTC))
    transaction = _create_example_transaction(database_session)

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link",
        json={"transaction_id": transaction.id},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 409
    assert "locked" in response.json()["detail"]


# 📋 POST /api/v1/receipts/{id}/unlink — Unlink Receipt from Payment


def should_unlink_receipt_from_payment(api_client, database_session):
    from app.models.receipt_transaction_link import ReceiptTransactionLink

    receipt = _create_example_receipt(database_session, amount=Decimal("100.00"))
    transaction = _create_example_transaction(
        database_session,
        amount=Decimal("100.00"),
    )
    link = ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id)
    database_session.add(link)
    database_session.flush()

    response = api_client.post(f"/api/v1/receipts/{receipt.id}/unlink", headers=AUTH_HEADERS)
    assert response.status_code == 200

    # Verify link was removed from junction table
    from sqlalchemy import select

    remaining_link = database_session.execute(
        select(ReceiptTransactionLink).where(ReceiptTransactionLink.receipt_id == receipt.id)
    ).scalar_one_or_none()
    assert remaining_link is None


def should_create_audit_log_on_unlink(api_client, database_session):
    from app.models.receipt_transaction_link import ReceiptTransactionLink

    receipt = _create_example_receipt(database_session, amount=Decimal("100.00"))
    transaction = _create_example_transaction(database_session, amount=Decimal("100.00"))
    link = ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id)
    database_session.add(link)
    database_session.flush()

    response = api_client.post(f"/api/v1/receipts/{receipt.id}/unlink", headers=AUTH_HEADERS)
    assert response.status_code == 200

    from sqlalchemy import select

    audit_logs = database_session.execute(select(ReceiptAuditLog).where(ReceiptAuditLog.receipt_id == receipt.id)).scalars().all()
    assert any(log.action == ReceiptAuditAction.UNLINKED for log in audit_logs)


def should_reject_unlink_of_locked_receipt(api_client, database_session):
    receipt = _create_example_receipt(database_session, locked_at=datetime.now(UTC))

    response = api_client.post(f"/api/v1/receipts/{receipt.id}/unlink", headers=AUTH_HEADERS)
    assert response.status_code == 409
    assert "locked" in response.json()["detail"]


# 📋 POST /api/v1/receipts/lock — Lock Receipts in Date Range


def should_lock_receipts_in_date_range(api_client, database_session):
    receipt1 = _create_example_receipt(database_session, receipt_date=date(2025, 1, 15), counterparty="Jan 2025")
    receipt2 = _create_example_receipt(
        database_session,
        receipt_date=date(2025, 6, 15),
        counterparty="Jun 2025",
        receipt_number="INV-002",
    )
    _create_example_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        counterparty="Jan 2026",
        receipt_number="INV-003",
    )  # Outside range

    response = api_client.post(
        "/api/v1/receipts/lock",
        json={"start_date": "2025-01-01", "end_date": "2025-12-31"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["locked_count"] == 2

    # Verify receipts locked
    database_session.refresh(receipt1)
    database_session.refresh(receipt2)
    assert receipt1.is_locked is True
    assert receipt1.locked_at is not None
    assert receipt2.is_locked is True


def should_not_relock_already_locked_receipts(api_client, database_session):
    _create_example_receipt(
        database_session,
        receipt_date=date(2025, 1, 15),
        locked_at=datetime.now(UTC),
    )

    response = api_client.post(
        "/api/v1/receipts/lock",
        json={"start_date": "2025-01-01", "end_date": "2025-12-31"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    # Already locked, so count is 0
    assert response.json()["locked_count"] == 0


def should_create_audit_logs_on_lock(api_client, database_session):
    receipt = _create_example_receipt(database_session, receipt_date=date(2025, 6, 15))

    response = api_client.post(
        "/api/v1/receipts/lock",
        json={"start_date": "2025-01-01", "end_date": "2025-12-31"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200

    from sqlalchemy import select

    audit_logs = database_session.execute(select(ReceiptAuditLog).where(ReceiptAuditLog.receipt_id == receipt.id)).scalars().all()
    assert any(log.action == ReceiptAuditAction.LOCKED for log in audit_logs)


# 📋 GET /api/v1/receipts/{id}/suggestions — Match Suggestions


def should_suggest_matches_by_amount_and_date(api_client, database_session):
    receipt = _create_example_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    # Matching transaction: same amount, same date
    _create_example_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        counterparty="Match Co",
    )
    # Non-matching: different amount
    _create_example_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("50.00"),
        counterparty="No Match",
    )

    response = api_client.get(f"/api/v1/receipts/{receipt.id}/suggestions", headers=AUTH_HEADERS)
    assert response.status_code == 200
    suggestions = response.json()
    assert len(suggestions) == 1
    assert suggestions[0]["counterparty"] == "Match Co"
    assert suggestions[0]["confidence"] == 1.0  # 0.6 amount + 0.4 same date


def should_not_suggest_matches_outside_date_window(api_client, database_session):
    receipt = _create_example_receipt(
        database_session,
        receipt_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    # Transaction outside 5-day window
    _create_example_transaction(
        database_session,
        transaction_date=date(2026, 1, 25),  # 10 days apart
        amount=Decimal("100.00"),
        counterparty="Too Far",
    )

    response = api_client.get(f"/api/v1/receipts/{receipt.id}/suggestions", headers=AUTH_HEADERS)
    assert response.status_code == 200
    suggestions = response.json()
    assert len(suggestions) == 0


def should_not_suggest_already_linked_transactions(api_client, database_session):
    from app.models.receipt_transaction_link import ReceiptTransactionLink

    receipt1 = _create_example_receipt(database_session, receipt_date=date(2026, 1, 15), amount=Decimal("100.00"))
    receipt2 = _create_example_receipt(
        database_session,
        receipt_date=date(2026, 1, 16),
        amount=Decimal("100.00"),
        receipt_number="INV-002",
    )

    # Transaction linked to receipt1 via junction table
    transaction = _create_example_transaction(
        database_session,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
    )
    link = ReceiptTransactionLink(receipt_id=receipt1.id, transaction_id=transaction.id)
    database_session.add(link)
    database_session.flush()

    # Get suggestions for receipt2 - should not include the linked transaction
    response = api_client.get(f"/api/v1/receipts/{receipt2.id}/suggestions", headers=AUTH_HEADERS)
    assert response.status_code == 200
    suggestions = response.json()
    assert len(suggestions) == 0


# 📋 Duplicate OMS Receipt Handling


def should_reject_duplicate_oms_receipt(database_session, example_user):
    """Database safety net: unique index prevents duplicate OMS order IDs."""
    from sqlalchemy.exc import IntegrityError

    _create_example_receipt(
        database_session,
        oms_order_id="BB-12345",
        counterparty="First",
    )

    with pytest.raises(IntegrityError):
        _create_example_receipt(
            database_session,
            oms_order_id="BB-12345",  # Same OMS order ID
            counterparty="Duplicate",
            receipt_number="INV-002",
        )
        database_session.flush()


def should_allow_soft_deleted_and_new_with_same_oms_id(database_session, example_user):
    """Soft-deleted receipts should not block re-import with same OMS order ID."""
    # Create and soft-delete a receipt
    deleted_receipt = _create_example_receipt(
        database_session,
        oms_order_id="BB-REIMPORT",
        counterparty="Deleted",
    )
    deleted_receipt.deleted_at = datetime.now(UTC)
    database_session.flush()

    # Create new receipt with same OMS order ID - should work
    new_receipt = _create_example_receipt(
        database_session,
        oms_order_id="BB-REIMPORT",
        counterparty="Re-imported",
        receipt_number="INV-002",
    )
    database_session.flush()

    assert new_receipt.id != deleted_receipt.id
    assert new_receipt.oms_order_id == deleted_receipt.oms_order_id


# 📋 Auth — Require Authentication Headers


def should_reject_request_without_user_headers(api_client):
    """Missing X-User-ID header defaults to empty → 401 Unauthorized."""
    response = api_client.get("/api/v1/receipts")
    assert response.status_code == 401


def should_reject_create_without_user_headers(api_client):
    """Missing X-User-ID header defaults to empty → 401 Unauthorized."""
    response = api_client.post(
        "/api/v1/receipts",
        json={
            "receipt_number": "UNAUTH",
            "date": "2026-01-20",
            "counterparty": "Unauthorized",
            "line_items": [{"amount": "50.00"}],
        },
    )
    assert response.status_code == 401


# 📋 File Upload — Storage Backend Integration (two-step: create receipt, then upload file)


@patch("app.services.receipt_storage.get_storage_backend")
def should_upload_file_to_storage(mock_get_backend, api_client, database_session):
    """File upload stores to storage backend and records object name + hash in DB."""
    from io import BytesIO

    from sqlalchemy import select

    fake_backend = MagicMock()
    fake_backend.upload.return_value = f"receipts/2026/{FAKE_PDF_HASH}.pdf"
    mock_get_backend.return_value = fake_backend

    # Step 1: Create receipt via JSON
    create_response = api_client.post(
        "/api/v1/receipts",
        json={
            "receipt_number": "FILE-001",
            "date": "2026-01-20",
            "counterparty": "File Supplier",
            "line_items": [{"amount": "99.00"}],
        },
        headers=AUTH_HEADERS,
    )
    assert create_response.status_code == 201
    receipt_id = create_response.json()["id"]

    # Step 2: Upload file
    response = api_client.post(
        f"/api/v1/receipts/{receipt_id}/upload",
        files={"file": ("invoice.pdf", BytesIO(FAKE_PDF_CONTENT), "application/pdf")},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["has_file"] is True

    # Verify DB state
    receipt = database_session.execute(select(Receipt).where(Receipt.id == receipt_id)).scalar_one()
    assert receipt.file_hash == FAKE_PDF_HASH
    assert receipt.file_storage_id is not None
    assert "receipts/" in receipt.file_storage_id
    assert receipt.file_mime_type == "application/pdf"
    assert receipt.file_original_name == "invoice.pdf"


@patch("app.services.receipt_storage.get_storage_backend")
def should_skip_upload_if_blob_exists(mock_get_backend, api_client):
    """Content-addressable dedup: skip upload when blob already exists."""
    from io import BytesIO

    fake_backend = MagicMock()
    fake_backend.upload.return_value = f"receipts/2026/{FAKE_PDF_HASH}.pdf"
    mock_get_backend.return_value = fake_backend

    # Step 1: Create receipt via JSON
    create_response = api_client.post(
        "/api/v1/receipts",
        json={
            "receipt_number": "DEDUP-001",
            "date": "2026-01-20",
            "counterparty": "Dedup Test",
            "line_items": [{"amount": "50.00"}],
        },
        headers=AUTH_HEADERS,
    )
    assert create_response.status_code == 201
    receipt_id = create_response.json()["id"]

    # Step 2: Upload file
    response = api_client.post(
        f"/api/v1/receipts/{receipt_id}/upload",
        files={"file": ("invoice.pdf", BytesIO(FAKE_PDF_CONTENT), "application/pdf")},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200

    # Backend.upload handles dedup internally (checks exists())
    # We verify it was called exactly once (the backend handles skip logic)
    fake_backend.upload.assert_called_once()


def should_reject_oversized_file(api_client):
    """Files exceeding 10 MB are rejected with 400."""
    from io import BytesIO

    oversized_content = b"%PDF-1.4 " + b"x" * (10 * 1024 * 1024 + 1)  # Just over 10 MB

    # Step 1: Create receipt via JSON
    create_response = api_client.post(
        "/api/v1/receipts",
        json={
            "receipt_number": "BIG-001",
            "date": "2026-01-20",
            "counterparty": "Big File Co",
            "line_items": [{"amount": "50.00"}],
        },
        headers=AUTH_HEADERS,
    )
    assert create_response.status_code == 201
    receipt_id = create_response.json()["id"]

    # Step 2: Upload oversized file
    response = api_client.post(
        f"/api/v1/receipts/{receipt_id}/upload",
        files={"file": ("big.pdf", BytesIO(oversized_content), "application/pdf")},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "maximum size" in response.json()["detail"]


def should_reject_invalid_mime_type(api_client):
    """Non-allowed MIME types (e.g., .exe) are rejected with 400."""
    from io import BytesIO

    exe_content = b"MZ\x90\x00 fake executable"  # PE magic bytes

    # Step 1: Create receipt via JSON
    create_response = api_client.post(
        "/api/v1/receipts",
        json={
            "receipt_number": "EXE-001",
            "date": "2026-01-20",
            "counterparty": "Malware Inc",
            "line_items": [{"amount": "50.00"}],
        },
        headers=AUTH_HEADERS,
    )
    assert create_response.status_code == 201
    receipt_id = create_response.json()["id"]

    # Step 2: Upload invalid file type
    response = api_client.post(
        f"/api/v1/receipts/{receipt_id}/upload",
        files={"file": ("malware.exe", BytesIO(exe_content), "application/x-msdownload")},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "Invalid file type" in response.json()["detail"]


@patch("app.services.receipt_storage.get_storage_backend")
def should_create_audit_log_on_upload(mock_get_backend, api_client, database_session):
    """FILE_UPLOADED audit action is logged when file is attached."""
    from io import BytesIO

    from sqlalchemy import select

    fake_backend = MagicMock()
    fake_backend.upload.return_value = f"receipts/2026/{FAKE_PDF_HASH}.pdf"
    mock_get_backend.return_value = fake_backend

    # Step 1: Create receipt via JSON
    create_response = api_client.post(
        "/api/v1/receipts",
        json={
            "receipt_number": "AUDIT-UPLOAD",
            "date": "2026-01-20",
            "counterparty": "Audit Upload Co",
            "line_items": [{"amount": "75.00"}],
        },
        headers=AUTH_HEADERS,
    )
    assert create_response.status_code == 201
    receipt_id = create_response.json()["id"]

    # Step 2: Upload file
    response = api_client.post(
        f"/api/v1/receipts/{receipt_id}/upload",
        files={"file": ("receipt.pdf", BytesIO(FAKE_PDF_CONTENT), "application/pdf")},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200

    audit_logs = database_session.execute(select(ReceiptAuditLog).where(ReceiptAuditLog.receipt_id == receipt_id)).scalars().all()
    actions = [log.action for log in audit_logs]
    assert ReceiptAuditAction.CREATED in actions
    assert ReceiptAuditAction.FILE_UPLOADED in actions


# 📋 File Download — Storage Backend Integration


@patch("app.services.receipt_storage.get_storage_backend")
def should_download_file_from_storage(mock_get_backend, api_client, database_session):
    """Download endpoint fetches from storage backend and verifies hash."""
    # Create a receipt with file metadata directly in DB
    receipt = _create_example_receipt(
        database_session,
        counterparty="Download Co",
        receipt_number="DL-001",
    )
    receipt.file_hash = FAKE_PDF_HASH
    receipt.file_storage_id = f"test-user-id/2026/{FAKE_PDF_HASH}.pdf"
    receipt.file_original_name = "receipt.pdf"
    receipt.file_mime_type = "application/pdf"
    database_session.flush()

    fake_backend = MagicMock()
    fake_backend.download.return_value = FAKE_PDF_CONTENT
    mock_get_backend.return_value = fake_backend

    response = api_client.get(f"/api/v1/receipts/{receipt.id}/file", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.content == FAKE_PDF_CONTENT
    assert response.headers["content-type"] == "application/pdf"
    assert "receipt.pdf" in response.headers["content-disposition"]


@patch("app.services.receipt_storage.get_storage_backend")
def should_verify_hash_on_download(mock_get_backend, api_client, database_session):
    """Hash mismatch on download returns 500 (file integrity violation)."""
    receipt = _create_example_receipt(
        database_session,
        counterparty="Tampered Co",
        receipt_number="TAMPER-001",
    )
    receipt.file_hash = FAKE_PDF_HASH
    receipt.file_storage_id = f"test-user-id/2026/{FAKE_PDF_HASH}.pdf"
    receipt.file_original_name = "receipt.pdf"
    receipt.file_mime_type = "application/pdf"
    database_session.flush()

    fake_backend = MagicMock()
    fake_backend.download.return_value = b"tampered content - not the original file"
    mock_get_backend.return_value = fake_backend

    response = api_client.get(f"/api/v1/receipts/{receipt.id}/file", headers=AUTH_HEADERS)
    assert response.status_code == 500
    assert "integrity" in response.json()["detail"].lower()


def should_return_404_for_receipt_without_file(api_client, database_session):
    """Download returns 404 when receipt has no attached file."""
    receipt = _create_example_receipt(database_session, counterparty="No File Co", receipt_number="NOFILE-001")

    response = api_client.get(f"/api/v1/receipts/{receipt.id}/file", headers=AUTH_HEADERS)
    assert response.status_code == 404
    assert "no file" in response.json()["detail"].lower()


@patch("app.services.receipt_storage.get_storage_backend")
def should_create_audit_log_on_download(mock_get_backend, api_client, database_session):
    """FILE_DOWNLOADED audit action is logged on successful download."""
    from sqlalchemy import select

    receipt = _create_example_receipt(
        database_session,
        counterparty="Audit Download Co",
        receipt_number="AUDIT-DL-001",
    )
    receipt.file_hash = FAKE_PDF_HASH
    receipt.file_storage_id = f"test-user-id/2026/{FAKE_PDF_HASH}.pdf"
    receipt.file_original_name = "receipt.pdf"
    receipt.file_mime_type = "application/pdf"
    database_session.flush()

    fake_backend = MagicMock()
    fake_backend.download.return_value = FAKE_PDF_CONTENT
    mock_get_backend.return_value = fake_backend

    response = api_client.get(f"/api/v1/receipts/{receipt.id}/file", headers=AUTH_HEADERS)
    assert response.status_code == 200

    audit_logs = database_session.execute(select(ReceiptAuditLog).where(ReceiptAuditLog.receipt_id == receipt.id)).scalars().all()
    assert any(log.action == ReceiptAuditAction.FILE_DOWNLOADED for log in audit_logs)


# 📋 POST /api/v1/receipts/extract — Document Extraction


@patch("app.routers.receipts.extract_from_document")
def should_return_extraction_result_for_pdf_upload(mock_extract, api_client):
    """PDF upload → ExtractionResult with extracted fields."""
    from io import BytesIO

    from app.schemas.extraction import ExtractionResult

    mock_extract.return_value = ExtractionResult(
        source="zugferd",
        receipt_number="RE-2026-001",
        counterparty="Muster GmbH",
        total_gross=Decimal("119.00"),
    )

    response = api_client.post(
        "/api/v1/receipts/extract",
        files={"file": ("invoice.pdf", BytesIO(FAKE_PDF_CONTENT), "application/pdf")},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "zugferd"
    assert body["receipt_number"] == "RE-2026-001"
    assert body["counterparty"] == "Muster GmbH"
    assert body["total_gross"] == "119.00"
    mock_extract.assert_called_once()


@patch("app.routers.receipts.extract_from_document")
def should_accept_xml_upload_for_xrechnung(mock_extract, api_client):
    """XML upload (XRechnung) → ExtractionResult from CII parser."""
    from io import BytesIO

    from app.schemas.extraction import ExtractionResult

    xrechnung_xml = b'<?xml version="1.0"?><rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"><rsm:ExchangedDocument/></rsm:CrossIndustryInvoice>'

    mock_extract.return_value = ExtractionResult(
        source="zugferd",
        receipt_number="XR-001",
    )

    response = api_client.post(
        "/api/v1/receipts/extract",
        files={"file": ("xrechnung.xml", BytesIO(xrechnung_xml), "application/xml")},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "zugferd"
    assert body["receipt_number"] == "XR-001"
    mock_extract.assert_called_once()


def should_reject_unsupported_file_type(api_client):
    """Non-allowed MIME type → 400."""
    from io import BytesIO

    response = api_client.post(
        "/api/v1/receipts/extract",
        files={"file": ("data.csv", BytesIO(b"a,b,c\n1,2,3"), "text/csv")},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def should_reject_oversized_extraction_file(api_client):
    """File exceeding 10 MB on extract endpoint → 400."""
    from io import BytesIO

    oversized_content = b"%PDF-1.4 " + b"x" * (10 * 1024 * 1024 + 1)

    response = api_client.post(
        "/api/v1/receipts/extract",
        files={"file": ("huge.pdf", BytesIO(oversized_content), "application/pdf")},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "too large" in response.json()["detail"].lower()


@patch("app.routers.receipts.extract_from_document")
def should_enforce_global_rate_limit(mock_extract, api_client):
    """More than configured rate limit → 429 (instance-wide, not per-user)."""
    from io import BytesIO

    from app.core.rate_limit import limiter
    from app.schemas.extraction import ExtractionResult

    mock_extract.return_value = ExtractionResult(source="manual")
    fake_pdf = b"%PDF-1.4 fake content"

    # Reset limiter storage to avoid state leakage between tests
    limiter.reset()

    # Patch the config value that get_extraction_rate_limit() reads
    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value.extraction_rate_limit = "2/minute"

        for _ in range(2):
            response = api_client.post(
                "/api/v1/receipts/extract",
                files={"file": ("invoice.pdf", BytesIO(fake_pdf), "application/pdf")},
                headers=AUTH_HEADERS,
            )
            assert response.status_code == 200

        # Third request exceeds rate limit
        response = api_client.post(
            "/api/v1/receipts/extract",
            files={"file": ("invoice.pdf", BytesIO(fake_pdf), "application/pdf")},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 429


# 📋 Payment Status — Automatic Update on Link/Unlink


def should_set_payment_status_to_paid_on_link(api_client, database_session):
    """Linking receipt to payment sets payment_status to 'paid'."""
    receipt = _create_example_receipt(database_session, amount=Decimal("100.00"))
    transaction = _create_example_transaction(database_session, amount=Decimal("100.00"))

    # Verify initial status
    assert receipt.payment_status == "unpaid"

    # Link the receipt
    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link",
        json={"transaction_id": transaction.id},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()

    # Verify status changed
    assert body["payment_status"] == "paid"


def should_set_payment_status_to_unpaid_on_unlink(api_client, database_session):
    """Unlinking receipt from payment sets payment_status to 'unpaid'."""
    from app.models.receipt_transaction_link import ReceiptTransactionLink

    receipt = _create_example_receipt(database_session, amount=Decimal("100.00"))
    transaction = _create_example_transaction(database_session, amount=Decimal("100.00"))

    # Create link directly
    link = ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id)
    database_session.add(link)
    receipt.payment_status = "paid"
    database_session.flush()

    # Unlink
    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/unlink",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["payment_status"] == "unpaid"


def should_set_payment_status_to_partial_on_incomplete_link(api_client, database_session):
    """Linking receipt to transaction covering only part of the amount sets 'partial'."""
    # Receipt total = 100.00, but linked transaction = 40.00 → partial
    receipt = _create_example_receipt(database_session, amount=Decimal("100.00"))
    transaction = _create_example_transaction(database_session, amount=Decimal("40.00"))

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link",
        json={"transaction_id": transaction.id},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["payment_status"] == "partial"
    assert Decimal(body["open_amount"]) == Decimal("60.00")


def should_filter_receipts_by_payment_status(api_client, database_session):
    """GET /receipts with payment_status filter returns only matching receipts."""
    from app.models.receipt_transaction_link import ReceiptTransactionLink

    # Create paid receipt
    paid_receipt = _create_example_receipt(
        database_session,
        counterparty="Paid Customer",
        receipt_number="PAID-001",
    )
    transaction = _create_example_transaction(database_session, amount=Decimal("100.00"))
    link = ReceiptTransactionLink(receipt_id=paid_receipt.id, transaction_id=transaction.id)
    database_session.add(link)
    paid_receipt.payment_status = "paid"
    database_session.flush()

    # Create unpaid receipt
    _create_example_receipt(
        database_session,
        counterparty="Unpaid Customer",
        receipt_number="UNPAID-001",
    )

    # Filter by unpaid
    response = api_client.get("/api/v1/receipts?payment_status=unpaid", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["receipts"][0]["counterparty"] == "Unpaid Customer"

    # Filter by paid
    response = api_client.get("/api/v1/receipts?payment_status=paid", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["receipts"][0]["counterparty"] == "Paid Customer"


def should_include_payment_status_in_receipt_response(api_client, database_session):
    """Receipt response includes payment_status field."""
    receipt = _create_example_receipt(database_session)

    response = api_client.get(f"/api/v1/receipts/{receipt.id}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()

    assert "payment_status" in body
    assert body["payment_status"] == "unpaid"


# 📋 POST /api/v1/receipts/{id}/record-payment — Manual Payment Recording


def should_record_manual_payment_for_receipt(api_client, database_session):
    """Record-payment creates transaction, link, and sets status to paid."""
    from app.models.source import SourceType, TransactionSourceConfig

    # Create source config
    source = TransactionSourceConfig(
        id="test-bank-account",
        user_id=None,
        name="Test Bank",
        type=SourceType.CSV_PARSER,
        check_account_id=1210,
    )
    database_session.add(source)
    database_session.flush()

    receipt = _create_example_receipt(
        database_session,
        amount=Decimal("150.00"),
        counterparty="Invoice Customer",
    )

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/record-payment",
        json={
            "source_config_id": "test-bank-account",
            "date": "2026-01-20",
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201
    body = response.json()

    assert body["payment_status"] == "paid"
    # Verify transaction was created (via link)
    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from sqlalchemy import select

    link = database_session.execute(select(ReceiptTransactionLink).where(ReceiptTransactionLink.receipt_id == receipt.id)).scalar_one()
    assert link is not None


def should_create_negative_transaction_for_expense_receipt(api_client, database_session):
    """Record-payment on expense receipt creates transaction with negative amount."""
    from app.models.source import SourceType, TransactionSourceConfig
    from app.models.transaction import Transaction

    source = TransactionSourceConfig(
        id="expense-bank",
        user_id=None,
        name="Expense Bank",
        type=SourceType.CSV_PARSER,
        check_account_id=1211,
    )
    database_session.add(source)
    database_session.flush()

    receipt = _create_example_receipt(
        database_session,
        receipt_type=ReceiptType.EXPENSE,
        amount=Decimal("75.50"),
        counterparty="Supplier",
        receipt_number="EXP-001",
    )

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/record-payment",
        json={
            "source_config_id": "expense-bank",
            "date": "2026-01-20",
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201

    # Find the created transaction via link
    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from sqlalchemy import select

    link = database_session.execute(select(ReceiptTransactionLink).where(ReceiptTransactionLink.receipt_id == receipt.id)).scalar_one()
    transaction = database_session.get(Transaction, link.transaction_id)

    # Expense → negative amount
    assert transaction.amount == Decimal("-75.50")


def should_create_positive_transaction_for_revenue_receipt(api_client, database_session):
    """Record-payment on revenue receipt creates transaction with positive amount."""
    from app.models.source import SourceType, TransactionSourceConfig
    from app.models.transaction import Transaction

    source = TransactionSourceConfig(
        id="revenue-bank",
        user_id=None,
        name="Revenue Bank",
        type=SourceType.CSV_PARSER,
        check_account_id=1212,
    )
    database_session.add(source)
    database_session.flush()

    receipt = _create_example_receipt(
        database_session,
        receipt_type=ReceiptType.REVENUE,
        amount=Decimal("200.00"),
        counterparty="Customer",
    )

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/record-payment",
        json={
            "source_config_id": "revenue-bank",
            "date": "2026-01-20",
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201

    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from sqlalchemy import select

    link = database_session.execute(select(ReceiptTransactionLink).where(ReceiptTransactionLink.receipt_id == receipt.id)).scalar_one()
    transaction = database_session.get(Transaction, link.transaction_id)

    # Revenue → positive amount
    assert transaction.amount == Decimal("200.00")


def should_use_receipt_defaults_for_record_payment(api_client, database_session):
    """Record-payment uses receipt amount and counterparty as defaults."""
    from app.models.source import SourceType, TransactionSourceConfig
    from app.models.transaction import Transaction

    source = TransactionSourceConfig(
        id="default-bank",
        user_id=None,
        name="Default Bank",
        type=SourceType.CSV_PARSER,
        check_account_id=1213,
    )
    database_session.add(source)
    database_session.flush()

    receipt = _create_example_receipt(
        database_session,
        amount=Decimal("123.45"),
        counterparty="Default Customer",
        receipt_number="DEF-001",
    )

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/record-payment",
        json={
            "source_config_id": "default-bank",
            "date": "2026-01-20",
            # amount and counterparty not provided — should use receipt values
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201

    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from sqlalchemy import select

    link = database_session.execute(select(ReceiptTransactionLink).where(ReceiptTransactionLink.receipt_id == receipt.id)).scalar_one()
    transaction = database_session.get(Transaction, link.transaction_id)

    assert transaction.amount == Decimal("123.45")
    assert transaction.counterparty == "Default Customer"
    assert transaction.description == "Zahlung Beleg #DEF-001"


def should_use_custom_values_for_record_payment(api_client, database_session):
    """Record-payment accepts custom amount, counterparty, and description."""
    from app.models.source import SourceType, TransactionSourceConfig
    from app.models.transaction import Transaction

    source = TransactionSourceConfig(
        id="custom-bank",
        user_id=None,
        name="Custom Bank",
        type=SourceType.CSV_PARSER,
        check_account_id=1214,
    )
    database_session.add(source)
    database_session.flush()

    receipt = _create_example_receipt(
        database_session,
        amount=Decimal("100.00"),
        counterparty="Original Customer",
    )

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/record-payment",
        json={
            "source_config_id": "custom-bank",
            "date": "2026-01-20",
            "amount": "50.00",  # Custom amount
            "counterparty": "Partial Payment Corp",
            "description": "Partial payment received",
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201

    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from sqlalchemy import select

    link = database_session.execute(select(ReceiptTransactionLink).where(ReceiptTransactionLink.receipt_id == receipt.id)).scalar_one()
    transaction = database_session.get(Transaction, link.transaction_id)

    assert transaction.amount == Decimal("50.00")
    assert transaction.counterparty == "Partial Payment Corp"
    assert transaction.description == "Partial payment received"


def should_allow_additional_payment_for_already_linked_receipt(api_client, database_session):
    """Record-payment allows M:N — additional payments for Sammelbeleg."""
    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from app.models.source import SourceType, TransactionSourceConfig

    source = TransactionSourceConfig(
        id="conflict-bank",
        user_id=None,
        name="Conflict Bank",
        type=SourceType.CSV_PARSER,
        check_account_id=1215,
    )
    database_session.add(source)
    database_session.flush()

    receipt = _create_example_receipt(database_session, amount=Decimal("200.00"))
    transaction = _create_example_transaction(database_session, amount=Decimal("100.00"))

    # Create existing link (partial payment)
    link = ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id)
    database_session.add(link)
    receipt.payment_status = "partial"
    database_session.flush()

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/record-payment",
        json={
            "source_config_id": "conflict-bank",
            "date": "2026-01-20",
            "amount": "100.00",
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201

    # Verify 2 links exist (M:N)
    from sqlalchemy import select

    links = database_session.execute(select(ReceiptTransactionLink).where(ReceiptTransactionLink.receipt_id == receipt.id)).scalars().all()
    assert len(links) == 2


def should_reject_record_payment_for_locked_receipt(api_client, database_session):
    """Record-payment returns 409 for locked receipt."""
    from app.models.source import SourceType, TransactionSourceConfig

    source = TransactionSourceConfig(
        id="locked-bank",
        user_id=None,
        name="Locked Bank",
        type=SourceType.CSV_PARSER,
        check_account_id=1216,
    )
    database_session.add(source)
    database_session.flush()

    receipt = _create_example_receipt(
        database_session,
        locked_at=datetime.now(UTC),
    )

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/record-payment",
        json={
            "source_config_id": "locked-bank",
            "date": "2026-01-20",
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 409
    assert "locked" in response.json()["detail"].lower()


def should_reject_record_payment_with_invalid_source_config(api_client, database_session):
    """Record-payment returns 400 for non-existent source_config_id."""
    receipt = _create_example_receipt(database_session)

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/record-payment",
        json={
            "source_config_id": "nonexistent-source",
            "date": "2026-01-20",
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


def should_reject_record_payment_with_future_date(api_client, database_session):
    """Record-payment returns 400 for date too far in the future."""
    from app.models.source import SourceType, TransactionSourceConfig

    source = TransactionSourceConfig(
        id="future-bank",
        user_id=None,
        name="Future Bank",
        type=SourceType.CSV_PARSER,
        check_account_id=1217,
    )
    database_session.add(source)
    database_session.flush()

    receipt = _create_example_receipt(database_session)

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/record-payment",
        json={
            "source_config_id": "future-bank",
            "date": "2030-12-31",  # Far in the future
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "future" in response.json()["detail"].lower()


def should_reject_record_payment_for_nonexistent_receipt(api_client, database_session):
    """Record-payment returns 404 for non-existent receipt."""
    from app.models.source import SourceType, TransactionSourceConfig

    source = TransactionSourceConfig(
        id="notfound-bank",
        user_id=None,
        name="NotFound Bank",
        type=SourceType.CSV_PARSER,
        check_account_id=1218,
    )
    database_session.add(source)
    database_session.flush()

    response = api_client.post(
        "/api/v1/receipts/nonexistent-receipt-id/record-payment",
        json={
            "source_config_id": "notfound-bank",
            "date": "2026-01-20",
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404


def should_create_audit_log_on_record_payment(api_client, database_session):
    """Record-payment creates PAYMENT_RECORDED audit log entry."""
    from app.models.source import SourceType, TransactionSourceConfig
    from sqlalchemy import select

    source = TransactionSourceConfig(
        id="audit-bank",
        user_id=None,
        name="Audit Bank",
        type=SourceType.CSV_PARSER,
        check_account_id=1219,
    )
    database_session.add(source)
    database_session.flush()

    receipt = _create_example_receipt(database_session)

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/record-payment",
        json={
            "source_config_id": "audit-bank",
            "date": "2026-01-20",
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201

    audit_logs = database_session.execute(select(ReceiptAuditLog).where(ReceiptAuditLog.receipt_id == receipt.id)).scalars().all()
    assert any(log.action == ReceiptAuditAction.PAYMENT_RECORDED for log in audit_logs)


# 🔗 POST /api/v1/receipts/{id}/link-bulk — Bulk Link (Sammelbeleg)


def should_bulk_link_transactions_to_receipt(api_client, database_session):
    """Bulk-link multiple transactions to a receipt (Sammelbeleg pattern)."""
    receipt = _create_example_receipt(database_session, amount=Decimal("100.00"))

    # Create 3 transactions that sum to receipt amount
    tx1 = _create_example_transaction(database_session, amount=Decimal("-30.00"))
    tx2 = _create_example_transaction(database_session, amount=Decimal("-40.00"))
    tx3 = _create_example_transaction(database_session, amount=Decimal("-30.00"))

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link-bulk",
        json={"transaction_ids": [tx1.id, tx2.id, tx3.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["linked_count"] == 3
    assert body["skipped_count"] == 0
    assert Decimal(body["receipt_open_amount"]) == Decimal("0.00")
    assert body["is_amount_matched"] is True


def should_skip_already_linked_transactions(api_client, database_session):
    """Bulk-link skips already-linked transactions (idempotent)."""
    from app.models.receipt_transaction_link import ReceiptTransactionLink

    receipt = _create_example_receipt(database_session, amount=Decimal("100.00"))
    tx1 = _create_example_transaction(database_session, amount=Decimal("-50.00"))
    tx2 = _create_example_transaction(database_session, amount=Decimal("-50.00"))

    # Pre-link tx1
    link = ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=tx1.id)
    database_session.add(link)
    database_session.commit()

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link-bulk",
        json={"transaction_ids": [tx1.id, tx2.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["linked_count"] == 1  # Only tx2 linked
    assert body["skipped_count"] == 1  # tx1 was already linked


def should_report_amount_mismatch_in_bulk_link(api_client, database_session):
    """Bulk-link reports amount difference when transactions don't match receipt."""
    receipt = _create_example_receipt(database_session, amount=Decimal("100.00"))

    # Create transactions that sum to 80 (20 less than receipt)
    tx1 = _create_example_transaction(database_session, amount=Decimal("-50.00"))
    tx2 = _create_example_transaction(database_session, amount=Decimal("-30.00"))

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link-bulk",
        json={"transaction_ids": [tx1.id, tx2.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["linked_count"] == 2
    assert Decimal(body["receipt_open_amount"]) == Decimal("20.00")
    assert Decimal(body["amount_difference"]) == Decimal("20.00")
    assert body["is_amount_matched"] is False


def should_reject_bulk_link_for_nonexistent_receipt(api_client, database_session):
    """Bulk-link returns 404 for non-existent receipt."""
    tx = _create_example_transaction(database_session, amount=Decimal("-10.00"))

    response = api_client.post(
        "/api/v1/receipts/nonexistent-receipt-id/link-bulk",
        json={"transaction_ids": [tx.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404


def should_reject_bulk_link_for_nonexistent_transactions(api_client, database_session):
    """Bulk-link returns 404 when some transaction IDs don't exist."""
    receipt = _create_example_receipt(database_session)

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link-bulk",
        json={
            "transaction_ids": [
                "00000000-0000-0000-0000-000000000098",
                "00000000-0000-0000-0000-000000000099",
            ]
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def should_reject_bulk_link_for_locked_receipt(api_client, database_session):
    """Bulk-link returns 403 for locked receipts (GoBD compliance)."""
    receipt = _create_example_receipt(database_session, locked_at=datetime.now(UTC))
    tx = _create_example_transaction(database_session, amount=Decimal("-10.00"))

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link-bulk",
        json={"transaction_ids": [tx.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 403
    assert "locked" in response.json()["detail"].lower()


def should_reject_bulk_link_with_empty_list(api_client, database_session):
    """Bulk-link returns 422 for empty transaction_ids list."""
    receipt = _create_example_receipt(database_session)

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link-bulk",
        json={"transaction_ids": []},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


def should_create_audit_log_on_bulk_link(api_client, database_session):
    """Bulk-link creates LINKED audit log entry with bulk metadata."""
    from sqlalchemy import select

    receipt = _create_example_receipt(database_session)
    tx1 = _create_example_transaction(database_session, amount=Decimal("-30.00"))
    tx2 = _create_example_transaction(database_session, amount=Decimal("-40.00"))

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/link-bulk",
        json={"transaction_ids": [tx1.id, tx2.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200

    audit_logs = (
        database_session.execute(
            select(ReceiptAuditLog).where(
                ReceiptAuditLog.receipt_id == receipt.id,
                ReceiptAuditLog.action == ReceiptAuditAction.LINKED,
            )
        )
        .scalars()
        .all()
    )

    # Find the bulk audit log
    bulk_logs = [log for log in audit_logs if log.details.get("bulk") is True]
    assert len(bulk_logs) == 1
    assert bulk_logs[0].details["linked_count"] == 2


# 🔗 POST /api/v1/receipts/create-and-link-bulk — Create + Bulk Link (Sammelbeleg)


def should_create_and_bulk_link_receipt(api_client, database_session):
    """Create receipt and bulk-link to transactions in one atomic operation."""
    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from sqlalchemy import select

    # Create 3 transactions
    tx1 = _create_example_transaction(database_session, amount=Decimal("-30.00"))
    tx2 = _create_example_transaction(database_session, amount=Decimal("-40.00"))
    tx3 = _create_example_transaction(database_session, amount=Decimal("-30.00"))

    response = api_client.post(
        "/api/v1/receipts/create-and-link-bulk",
        json={
            "receipt_number": "ETSY-2026-01",
            "date": "2026-01-31",
            "counterparty": "Etsy Ireland UC",
            "type": "expense",
            "line_items": [{"description": "Etsy Fees Januar", "amount": "100.00"}],
            "transaction_ids": [tx1.id, tx2.id, tx3.id],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201
    body = response.json()

    # Verify receipt created
    assert body["receipt_number"] == "ETSY-2026-01"
    assert body["counterparty"] == "Etsy Ireland UC"
    assert body["payment_status"] == "paid"

    # Verify all transactions linked
    assert len(body["linked_transactions"]) == 3

    # Verify links exist in DB
    links = database_session.execute(select(ReceiptTransactionLink).where(ReceiptTransactionLink.receipt_id == body["id"])).scalars().all()
    assert len(links) == 3


def should_reject_create_and_bulk_link_for_missing_transactions(api_client, database_session):
    """Create-and-link-bulk returns 404 when some transactions don't exist."""
    response = api_client.post(
        "/api/v1/receipts/create-and-link-bulk",
        json={
            "receipt_number": "TEST-001",
            "date": "2026-01-15",
            "counterparty": "Test",
            "line_items": [{"description": "Test", "amount": "50.00"}],
            "transaction_ids": [
                "00000000-0000-0000-0000-000000000098",
                "00000000-0000-0000-0000-000000000099",
            ],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def should_reject_create_and_bulk_link_with_empty_transaction_list(api_client, database_session):
    """Create-and-link-bulk returns 422 for empty transaction_ids."""
    response = api_client.post(
        "/api/v1/receipts/create-and-link-bulk",
        json={
            "receipt_number": "TEST-001",
            "date": "2026-01-15",
            "counterparty": "Test",
            "line_items": [{"description": "Test", "amount": "50.00"}],
            "transaction_ids": [],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


def should_create_audit_log_on_create_and_bulk_link(api_client, database_session):
    """Create-and-link-bulk creates audit logs for both CREATED and LINKED actions."""
    from sqlalchemy import select

    tx1 = _create_example_transaction(database_session, amount=Decimal("-25.00"))
    tx2 = _create_example_transaction(database_session, amount=Decimal("-25.00"))

    response = api_client.post(
        "/api/v1/receipts/create-and-link-bulk",
        json={
            "receipt_number": "AUDIT-001",
            "date": "2026-01-20",
            "counterparty": "Audit Test",
            "line_items": [{"description": "Test", "amount": "50.00"}],
            "transaction_ids": [tx1.id, tx2.id],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201
    receipt_id = response.json()["id"]

    # Check audit logs
    audit_logs = database_session.execute(select(ReceiptAuditLog).where(ReceiptAuditLog.receipt_id == receipt_id)).scalars().all()

    actions = [log.action for log in audit_logs]
    assert ReceiptAuditAction.CREATED in actions
    assert ReceiptAuditAction.LINKED in actions

    # Find bulk linked log
    bulk_logs = [log for log in audit_logs if log.details.get("bulk") is True]
    assert len(bulk_logs) == 1
    assert bulk_logs[0].details["linked_count"] == 2


# 🔗 POST /api/v1/receipts/{id}/unlink-bulk — Bulk Unlink


def should_bulk_unlink_specific_transactions(api_client, database_session):
    """Bulk-unlink removes only specified transactions."""
    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from sqlalchemy import select

    receipt = _create_example_receipt(database_session)
    tx1 = _create_example_transaction(database_session, amount=Decimal("-30.00"))
    tx2 = _create_example_transaction(database_session, amount=Decimal("-40.00"))
    tx3 = _create_example_transaction(database_session, amount=Decimal("-30.00"))

    # Create links
    for tx in [tx1, tx2, tx3]:
        database_session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=tx.id))
    database_session.commit()

    # Unlink only tx1 and tx2
    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/unlink-bulk",
        json={"transaction_ids": [tx1.id, tx2.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["unlinked_count"] == 2
    assert body["remaining_link_count"] == 1

    # Verify tx3 still linked
    links = database_session.execute(select(ReceiptTransactionLink).where(ReceiptTransactionLink.receipt_id == receipt.id)).scalars().all()
    assert len(links) == 1
    assert links[0].transaction_id == tx3.id


def should_reject_bulk_unlink_with_empty_list(api_client, database_session):
    """Bulk-unlink with empty list is rejected to prevent accidental mass-unlink."""
    receipt = _create_example_receipt(database_session)

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/unlink-bulk",
        json={"transaction_ids": []},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


def should_bulk_unlink_all_transactions_with_explicit_ids(api_client, database_session):
    """Bulk-unlink all transactions by providing all IDs explicitly."""
    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from sqlalchemy import select

    receipt = _create_example_receipt(database_session)
    tx1 = _create_example_transaction(database_session, amount=Decimal("-30.00"))
    tx2 = _create_example_transaction(database_session, amount=Decimal("-40.00"))

    # Create links
    for tx in [tx1, tx2]:
        database_session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=tx.id))
    database_session.commit()

    # Unlink all by providing explicit IDs
    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/unlink-bulk",
        json={"transaction_ids": [tx1.id, tx2.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["unlinked_count"] == 2
    assert body["remaining_link_count"] == 0

    # Verify no links remain
    links = database_session.execute(select(ReceiptTransactionLink).where(ReceiptTransactionLink.receipt_id == receipt.id)).scalars().all()
    assert len(links) == 0


def should_reject_bulk_unlink_for_locked_receipt(api_client, database_session):
    """Bulk-unlink returns 403 for locked receipts."""
    receipt = _create_example_receipt(database_session, locked_at=datetime.now(UTC))
    tx = _create_example_transaction(database_session, amount=Decimal("-50.00"))

    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/unlink-bulk",
        json={"transaction_ids": [tx.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 403
    assert "locked" in response.json()["detail"].lower()


def should_update_payment_status_after_bulk_unlink(api_client, database_session):
    """Bulk-unlink updates payment_status to unpaid when all links removed."""
    from app.models.receipt_transaction_link import ReceiptTransactionLink

    receipt = _create_example_receipt(database_session)
    tx = _create_example_transaction(database_session, amount=Decimal("-100.00"))

    # Create link
    database_session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=tx.id))
    receipt.payment_status = "paid"
    database_session.commit()

    # Unlink by providing explicit ID
    response = api_client.post(
        f"/api/v1/receipts/{receipt.id}/unlink-bulk",
        json={"transaction_ids": [tx.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200

    # Verify payment status updated
    database_session.refresh(receipt)
    assert receipt.payment_status == "unpaid"


# 🔍 GET /api/v1/receipts/{id}/suggestions?mode=bulk — Bulk Suggestions (Sammelbeleg)


def should_return_bulk_suggestions_for_receipt(api_client, database_session):
    """Bulk-suggestions finds unlinked transactions from same source and month."""
    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from app.models.source import SourceType, TransactionSourceConfig

    # Create Etsy source
    source = TransactionSourceConfig(
        id="etsy-source",
        user_id=None,
        name="Etsy Ireland UC",
        type=SourceType.MARKETPLACE_MAPPING,
        check_account_id=1201,
    )
    database_session.add(source)
    database_session.flush()

    # Create receipt for January 2026
    receipt = _create_example_receipt(
        database_session,
        receipt_date=date(2026, 1, 31),
        counterparty="Etsy Ireland UC",
        amount=Decimal("100.00"),
    )

    # Create transactions in January 2026
    _create_example_transaction(
        database_session,
        source_config_id="etsy-source",
        amount=Decimal("-30.00"),
        description="Transaction fee",
        transaction_date=date(2026, 1, 15),
    )
    _create_example_transaction(
        database_session,
        source_config_id="etsy-source",
        amount=Decimal("-40.00"),
        description="Listing fee",
        transaction_date=date(2026, 1, 20),
    )
    # This one is already linked (should be excluded)
    tx3 = _create_example_transaction(
        database_session,
        source_config_id="etsy-source",
        amount=Decimal("-30.00"),
        description="Processing fee",
        transaction_date=date(2026, 1, 25),
    )
    database_session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=tx3.id))
    database_session.commit()

    response = api_client.get(
        f"/api/v1/receipts/{receipt.id}/suggestions?mode=bulk",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()

    # Should find tx1 and tx2 (tx3 is already linked)
    assert len(body["transactions"]) == 2
    assert body["total"] == "70.00"
    assert body["receipt_amount"] == "100.00"
    assert body["difference"] == "30.00"
    assert body["is_amount_matched"] is False
    assert body["source_config_id"] == "etsy-source"


def should_return_empty_suggestions_when_no_source_found(api_client, database_session):
    """Bulk-suggestions returns empty when receipt counterparty doesn't match any source."""
    receipt = _create_example_receipt(
        database_session,
        receipt_date=date(2026, 1, 31),
        counterparty="Unknown Company",
        amount=Decimal("100.00"),
    )

    response = api_client.get(
        f"/api/v1/receipts/{receipt.id}/suggestions?mode=bulk",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()

    assert len(body["transactions"]) == 0
    assert body["total"] == "0.00"
    assert body["source_config_id"] is None


def should_group_transactions_by_type(api_client, database_session):
    """Bulk-suggestions groups transactions by type from description."""
    from app.models.source import SourceType, TransactionSourceConfig

    source = TransactionSourceConfig(
        id="etsy-grouping",
        user_id=None,
        name="Etsy Test",
        type=SourceType.MARKETPLACE_MAPPING,
        check_account_id=1201,
    )
    database_session.add(source)
    database_session.flush()

    receipt = _create_example_receipt(
        database_session,
        receipt_date=date(2026, 1, 31),
        counterparty="Etsy Test",
        amount=Decimal("100.00"),
    )

    # Create transactions with different types
    _create_example_transaction(
        database_session,
        source_config_id="etsy-grouping",
        amount=Decimal("-20.00"),
        description="Transaction fee for order",
        transaction_date=date(2026, 1, 15),
    )
    _create_example_transaction(
        database_session,
        source_config_id="etsy-grouping",
        amount=Decimal("-30.00"),
        description="Transaction fee again",
        transaction_date=date(2026, 1, 16),
    )
    _create_example_transaction(
        database_session,
        source_config_id="etsy-grouping",
        amount=Decimal("-10.00"),
        description="Listing fee",
        transaction_date=date(2026, 1, 17),
    )
    database_session.commit()

    response = api_client.get(
        f"/api/v1/receipts/{receipt.id}/suggestions?mode=bulk",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()

    # Check groups
    groups_by_type = {g["type"]: g for g in body["groups"]}
    assert "Transaction Fees" in groups_by_type
    assert groups_by_type["Transaction Fees"]["count"] == 2
    assert Decimal(groups_by_type["Transaction Fees"]["total"]) == Decimal("50.00")
    assert "Listing Fees" in groups_by_type
    assert groups_by_type["Listing Fees"]["count"] == 1


# --- Reverse Suggestions (POST /transactions/find-matching-receipts) ---


def should_find_matching_receipt_for_transactions(api_client, database_session):
    """Reverse suggestions: find unlinked receipts matching selected transaction total."""
    from app.models.source import SourceType, TransactionSourceConfig

    source = TransactionSourceConfig(
        id="etsy-reverse",
        user_id=None,
        name="Etsy Ireland UC",
        type=SourceType.MARKETPLACE_MAPPING,
        check_account_id=1201,
    )
    database_session.add(source)
    database_session.flush()

    # Create receipt with matching amount (241.66€)
    receipt = _create_example_receipt(
        database_session,
        receipt_date=date(2026, 1, 31),
        counterparty="Etsy Ireland UC",
        amount=Decimal("241.66"),
    )

    # Create 3 fee transactions totaling 241.66€
    tx1 = _create_example_transaction(
        database_session,
        source_config_id="etsy-reverse",
        amount=Decimal("-100.00"),
        description="Transaction fee",
        transaction_date=date(2026, 1, 15),
    )
    tx2 = _create_example_transaction(
        database_session,
        source_config_id="etsy-reverse",
        amount=Decimal("-91.66"),
        description="Processing fee",
        transaction_date=date(2026, 1, 16),
    )
    tx3 = _create_example_transaction(
        database_session,
        source_config_id="etsy-reverse",
        amount=Decimal("-50.00"),
        description="Listing fee",
        transaction_date=date(2026, 1, 17),
    )
    database_session.commit()

    response = api_client.post(
        "/api/v1/transactions/find-matching-receipts",
        json={"transaction_ids": [tx1.id, tx2.id, tx3.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["transaction_count"] == 3
    assert Decimal(body["selected_total"]) == Decimal("241.66")
    assert len(body["matching_receipts"]) >= 1

    # The 241.66€ receipt should be the top match
    top_match = body["matching_receipts"][0]
    assert top_match["id"] == receipt.id
    assert Decimal(top_match["amount"]) == Decimal("241.66")
    assert top_match["match_score"] > 0.5


def should_not_match_already_linked_receipts(api_client, database_session):
    """Reverse suggestions: already-linked receipts should not appear."""
    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from app.models.source import SourceType, TransactionSourceConfig

    source = TransactionSourceConfig(
        id="etsy-linked",
        user_id=None,
        name="Etsy Linked",
        type=SourceType.MARKETPLACE_MAPPING,
        check_account_id=1201,
    )
    database_session.add(source)
    database_session.flush()

    # Create receipt and link it to a different transaction
    receipt = _create_example_receipt(
        database_session,
        receipt_date=date(2026, 1, 31),
        counterparty="Etsy Linked",
        amount=Decimal("50.00"),
    )
    other_tx = _create_example_transaction(
        database_session,
        source_config_id="etsy-linked",
        amount=Decimal("-50.00"),
        description="Already linked",
        transaction_date=date(2026, 1, 10),
    )
    link = ReceiptTransactionLink(
        receipt_id=receipt.id,
        transaction_id=other_tx.id,
    )
    database_session.add(link)

    # Transaction to search with
    tx = _create_example_transaction(
        database_session,
        source_config_id="etsy-linked",
        amount=Decimal("-50.00"),
        description="Fee to match",
        transaction_date=date(2026, 1, 15),
    )
    database_session.commit()

    response = api_client.post(
        "/api/v1/transactions/find-matching-receipts",
        json={"transaction_ids": [tx.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()

    # The already-linked receipt should NOT appear
    matched_ids = [r["id"] for r in body["matching_receipts"]]
    assert receipt.id not in matched_ids


def should_reject_find_matching_for_nonexistent_transactions(api_client, database_session):
    """Reverse suggestions: 404 for non-existent transaction IDs."""
    response = api_client.post(
        "/api/v1/transactions/find-matching-receipts",
        json={"transaction_ids": ["00000000-0000-0000-0000-000000000099"]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404


def should_skip_receipts_with_large_amount_difference(api_client, database_session):
    """Reverse suggestions: receipts with >10€ difference are excluded."""
    # Create receipt for 500€
    _create_example_receipt(
        database_session,
        receipt_date=date(2026, 1, 31),
        counterparty="Big Receipt",
        amount=Decimal("500.00"),
    )

    # Transaction for 10€
    tx = _create_example_transaction(
        database_session,
        amount=Decimal("-10.00"),
        description="Small fee",
        transaction_date=date(2026, 1, 15),
    )
    database_session.commit()

    response = api_client.post(
        "/api/v1/transactions/find-matching-receipts",
        json={"transaction_ids": [tx.id]},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()

    # 500€ receipt should NOT match 10€ transaction
    assert len(body["matching_receipts"]) == 0
