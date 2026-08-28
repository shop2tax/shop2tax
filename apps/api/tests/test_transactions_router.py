"""Integration tests for the transactions router."""

from datetime import date
from decimal import Decimal

from tests.conftest import AUTH_HEADERS, _create_example_transaction

# 📋 GET /api/v1/transactions — List


def should_list_transactions_empty(api_client):
    response = api_client.get("/api/v1/transactions", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


def should_list_transactions_with_results(api_client, database_session):
    _create_example_transaction(database_session, counterparty="Acme Corp")
    _create_example_transaction(database_session, counterparty="Beta Inc", amount=Decimal("50.00"))

    response = api_client.get("/api/v1/transactions", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def should_list_transactions_with_pagination(api_client, database_session):
    for i in range(5):
        _create_example_transaction(
            database_session,
            counterparty=f"Vendor {i}",
            amount=Decimal(f"{(i + 1) * 10}.00"),
        )

    response = api_client.get("/api/v1/transactions?limit=2&offset=0", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2


def should_filter_by_source_config_id(api_client, database_session):
    from app.models.source import SourceType, TransactionSourceConfig

    etsy_source = TransactionSourceConfig(
        id="test-etsy-source",
        user_id=None,
        name="Etsy",
        type=SourceType.CSV_PARSER,
    )
    database_session.add(etsy_source)
    database_session.flush()

    _create_example_transaction(database_session)
    _create_example_transaction(database_session, source_config_id="test-etsy-source", counterparty="Etsy Buyer")

    response = api_client.get("/api/v1/transactions?source_config_id=test-etsy-source", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["counterparty"] == "Etsy Buyer"
    assert body["items"][0]["source_config_name"] == "Etsy"


def should_filter_by_is_private(api_client, database_session):
    _create_example_transaction(database_session, is_private=False, counterparty="Public Co")
    _create_example_transaction(database_session, is_private=True, counterparty="Private Co")

    response = api_client.get("/api/v1/transactions?is_private=true", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["counterparty"] == "Private Co"
    assert body["items"][0]["is_private"] is True


def should_filter_by_date_range(api_client, database_session):
    _create_example_transaction(database_session, transaction_date=date(2026, 1, 10), counterparty="January")
    _create_example_transaction(database_session, transaction_date=date(2026, 2, 15), counterparty="February")
    _create_example_transaction(database_session, transaction_date=date(2026, 3, 20), counterparty="March")

    response = api_client.get(
        "/api/v1/transactions?date_from=2026-02-01&date_to=2026-02-28",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["counterparty"] == "February"


def should_search_by_counterparty(api_client, database_session):
    _create_example_transaction(database_session, counterparty="Amazon Marketplace")
    _create_example_transaction(database_session, counterparty="DKB Bank")

    response = api_client.get("/api/v1/transactions?search=amazon", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["counterparty"] == "Amazon Marketplace"


def should_search_by_description(api_client, database_session):
    _create_example_transaction(database_session, description="Monthly subscription fee", counterparty="Vendor A")
    _create_example_transaction(database_session, description="One-time purchase", counterparty="Vendor B")

    response = api_client.get("/api/v1/transactions?search=subscription", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["description"] == "Monthly subscription fee"


def should_search_case_insensitive(api_client, database_session):
    _create_example_transaction(database_session, counterparty="UPPERCASE SHOP")

    response = api_client.get("/api/v1/transactions?search=uppercase", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["total"] == 1


def should_exclude_soft_deleted_from_list(api_client, database_session):
    from datetime import UTC, datetime

    transaction = _create_example_transaction(database_session, counterparty="Deleted Co")
    transaction.deleted_at = datetime.now(UTC)
    database_session.flush()

    _create_example_transaction(database_session, counterparty="Active Co")

    response = api_client.get("/api/v1/transactions", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["counterparty"] == "Active Co"


def should_list_all_transactions_in_shared_tenant(api_client, database_session):
    """Shared tenant: all users see all transactions."""
    from app.models import User

    other_user = User(id="other-user-id", provider_id="google-other", provider_type="google", email="other@example.com", name="Other User")
    database_session.add(other_user)
    database_session.flush()

    _create_example_transaction(database_session, user_id="test-user-id", counterparty="My Transaction")
    _create_example_transaction(database_session, user_id="other-user-id", counterparty="Other Transaction")

    response = api_client.get("/api/v1/transactions", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2


# 📋 GET /api/v1/transactions/{id} — Get Single


def should_get_transaction_by_id(api_client, database_session):
    transaction = _create_example_transaction(database_session, counterparty="Detail Corp", amount=Decimal("42.50"))

    response = api_client.get(f"/api/v1/transactions/{transaction.id}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == transaction.id
    assert body["counterparty"] == "Detail Corp"
    assert body["amount"] == "42.50"
    assert body["is_private"] is False


def should_return_404_for_missing_transaction(api_client):
    response = api_client.get("/api/v1/transactions/nonexistent-id", headers=AUTH_HEADERS)
    assert response.status_code == 404
    assert response.json()["detail"] == "Transaction 'nonexistent-id' not found"


def should_return_404_for_soft_deleted_transaction(api_client, database_session):
    from datetime import UTC, datetime

    transaction = _create_example_transaction(database_session)
    transaction.deleted_at = datetime.now(UTC)
    database_session.flush()

    response = api_client.get(f"/api/v1/transactions/{transaction.id}", headers=AUTH_HEADERS)
    assert response.status_code == 404


def should_get_any_users_transaction_in_shared_tenant(api_client, database_session):
    """Shared tenant: any user can see any transaction."""
    from app.models import User

    other_user = User(id="other-user-id-2", provider_id="google-other-2", provider_type="google", email="other2@example.com", name="Other User 2")
    database_session.add(other_user)
    database_session.flush()

    transaction = _create_example_transaction(database_session, user_id="other-user-id-2")

    response = api_client.get(f"/api/v1/transactions/{transaction.id}", headers=AUTH_HEADERS)
    assert response.status_code == 200


# 📋 POST /api/v1/transactions — Create


def _create_test_source(api_client, name="DKB", source_type="csv_mapping"):
    """Create a source config for testing and return its ID."""
    response = api_client.post(
        "/api/v1/sources",
        json={"name": name, "type": source_type},
        headers=AUTH_HEADERS,
    )
    return response.json()["id"]


def should_create_transaction(api_client):
    source_id = _create_test_source(api_client, name="DKB")
    payload = {
        "date": "2026-01-20",
        "amount": "150.00",
        "counterparty": "New Vendor",
        "description": "Office supplies",
        "source_config_id": source_id,
    }

    response = api_client.post("/api/v1/transactions", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 201
    body = response.json()
    assert body["counterparty"] == "New Vendor"
    assert body["amount"] == "150.00"
    assert body["description"] == "Office supplies"
    assert body["source_config_name"] == "DKB"
    assert body["is_private"] is False
    assert body["id"] is not None
    assert body["created_at"] is not None


def should_create_private_transaction(api_client):
    source_id = _create_test_source(api_client, name="DKB")
    payload = {
        "date": "2026-01-20",
        "amount": "30.00",
        "counterparty": "Personal Store",
        "description": "Private purchase",
        "source_config_id": source_id,
        "is_private": True,
    }

    response = api_client.post("/api/v1/transactions", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 201
    assert response.json()["is_private"] is True


def should_create_transaction_with_optional_fields(api_client):
    source_id = _create_test_source(api_client, name="Stripe")
    payload = {
        "date": "2026-02-01",
        "amount": "99.99",
        "counterparty": "Full Vendor",
        "description": "Full details order",
        "source_config_id": source_id,
        "source_reference": "ch_abc123",
        "notes": "Important note",
    }

    response = api_client.post("/api/v1/transactions", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 201
    body = response.json()
    assert body["source_reference"] == "ch_abc123"
    assert body["notes"] == "Important note"


# 📋 PATCH /api/v1/transactions/{id} — Update


def should_update_transaction_partially(api_client, database_session):
    transaction = _create_example_transaction(database_session, counterparty="Old Name", amount=Decimal("100.00"))

    response = api_client.patch(
        f"/api/v1/transactions/{transaction.id}",
        json={"counterparty": "New Name"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["counterparty"] == "New Name"
    # Amount should remain unchanged
    assert body["amount"] == "100.00"


def should_update_multiple_fields(api_client, database_session):
    transaction = _create_example_transaction(database_session)

    response = api_client.patch(
        f"/api/v1/transactions/{transaction.id}",
        json={
            "counterparty": "Updated Co",
            "description": "Updated description",
            "notes": "Added note",
            "amount": "200.00",
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["counterparty"] == "Updated Co"
    assert body["description"] == "Updated description"
    assert body["notes"] == "Added note"
    assert body["amount"] == "200.00"


def should_return_404_when_updating_missing_transaction(api_client):
    response = api_client.patch(
        "/api/v1/transactions/nonexistent-id",
        json={"counterparty": "Nope"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404


def should_reject_extra_fields_on_update(api_client, database_session):
    transaction = _create_example_transaction(database_session)

    response = api_client.patch(
        f"/api/v1/transactions/{transaction.id}",
        json={"unknown_field": "value"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


# 📋 DELETE /api/v1/transactions/{id} — Soft Delete


def should_soft_delete_transaction(api_client, database_session):
    transaction = _create_example_transaction(database_session)

    response = api_client.delete(f"/api/v1/transactions/{transaction.id}", headers=AUTH_HEADERS)
    assert response.status_code == 204

    # Verify it's no longer returned by GET
    get_response = api_client.get(f"/api/v1/transactions/{transaction.id}", headers=AUTH_HEADERS)
    assert get_response.status_code == 404


def should_soft_delete_excludes_from_list(api_client, database_session):
    transaction = _create_example_transaction(database_session)

    api_client.delete(f"/api/v1/transactions/{transaction.id}", headers=AUTH_HEADERS)

    response = api_client.get("/api/v1/transactions", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["total"] == 0


def should_return_404_when_deleting_missing_transaction(api_client):
    response = api_client.delete("/api/v1/transactions/nonexistent-id", headers=AUTH_HEADERS)
    assert response.status_code == 404


# 📋 PUT /api/v1/transactions/{id}/private — Toggle Private Flag


def should_mark_transaction_as_private(api_client, database_session):
    transaction = _create_example_transaction(database_session, is_private=False)

    response = api_client.put(
        f"/api/v1/transactions/{transaction.id}/private",
        json={"is_private": True},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["is_private"] is True


def should_unmark_transaction_as_private(api_client, database_session):
    transaction = _create_example_transaction(database_session, is_private=True)

    response = api_client.put(
        f"/api/v1/transactions/{transaction.id}/private",
        json={"is_private": False},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["is_private"] is False


def should_return_404_when_toggling_private_on_missing_transaction(api_client):
    response = api_client.put(
        "/api/v1/transactions/nonexistent-id/private",
        json={"is_private": True},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404


# 📋 POST /api/v1/transactions/import — Bulk Import


def should_import_transactions(api_client):
    source_id = _create_test_source(api_client, name="DKB")
    payload = {
        "source_config_id": source_id,
        "items": [
            {
                "date": "2026-01-10",
                "amount": "50.00",
                "counterparty": "Import Vendor A",
                "description": "First import",
            },
            {
                "date": "2026-01-11",
                "amount": "75.00",
                "counterparty": "Import Vendor B",
                "description": "Second import",
            },
        ],
        "skip_duplicates": True,
    }

    response = api_client.post("/api/v1/transactions/import", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 201
    body = response.json()
    assert body["imported_count"] == 2
    assert body["skipped_count"] == 0
    assert body["import_log_id"] is not None

    # Verify transactions exist in the list
    list_response = api_client.get("/api/v1/transactions", headers=AUTH_HEADERS)
    assert list_response.json()["total"] == 2


def should_import_with_source_reference(api_client):
    source_id = _create_test_source(api_client, name="Stripe")
    payload = {
        "source_config_id": source_id,
        "items": [
            {
                "date": "2026-03-01",
                "amount": "120.00",
                "counterparty": "Stripe Customer",
                "description": "Stripe payment",
                "source_reference": "pi_abc123",
            },
        ],
        "skip_duplicates": True,
    }

    response = api_client.post("/api/v1/transactions/import", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 201
    assert response.json()["imported_count"] == 1


def should_skip_duplicate_on_import(api_client):
    source_id = _create_test_source(api_client, name="DKB")

    items = [
        {
            "date": "2026-01-10",
            "amount": "50.00",
            "counterparty": "Duplicate Vendor",
            "description": "This is a duplicate",
        },
    ]

    # First import creates the transaction (with import_hash for hash-based dedup)
    first = api_client.post(
        "/api/v1/transactions/import",
        json={"source_config_id": source_id, "items": items, "skip_duplicates": True},
        headers=AUTH_HEADERS,
    )
    assert first.status_code == 201
    assert first.json()["imported_count"] == 1

    # Second import should be skipped as duplicate
    response = api_client.post(
        "/api/v1/transactions/import",
        json={"source_config_id": source_id, "items": items, "skip_duplicates": True},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["imported_count"] == 0
    assert body["skipped_count"] == 1


def should_import_duplicate_when_skip_duplicates_disabled(api_client):
    source_id = _create_test_source(api_client, name="DKB")

    items = [
        {
            "date": "2026-01-10",
            "amount": "50.00",
            "counterparty": "Duplicate Vendor",
            "description": "Allow duplicate",
        },
    ]

    # First import
    first = api_client.post(
        "/api/v1/transactions/import",
        json={"source_config_id": source_id, "items": items, "skip_duplicates": False},
        headers=AUTH_HEADERS,
    )
    assert first.status_code == 201
    assert first.json()["imported_count"] == 1

    # Second import with skip_duplicates=False should still import
    response = api_client.post(
        "/api/v1/transactions/import",
        json={"source_config_id": source_id, "items": items, "skip_duplicates": False},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 201
    assert response.json()["imported_count"] == 1


def should_import_sets_no_account(api_client):
    source_id = _create_test_source(api_client, name="Etsy", source_type="marketplace_mapping")
    payload = {
        "source_config_id": source_id,
        "items": [
            {
                "date": "2026-02-15",
                "amount": "25.00",
                "counterparty": "Etsy Buyer",
                "description": "Etsy sale",
            },
        ],
    }

    response = api_client.post("/api/v1/transactions/import", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 201

    # Verify imported transaction exists with no linked receipts
    list_response = api_client.get(f"/api/v1/transactions?source_config_id={source_id}", headers=AUTH_HEADERS)
    items = list_response.json()["items"]
    assert len(items) >= 1
    assert items[0]["linked_receipts"] == []


def should_import_empty_list(api_client):
    source_id = _create_test_source(api_client, name="DKB")
    payload = {
        "source_config_id": source_id,
        "items": [],
        "skip_duplicates": True,
    }

    response = api_client.post("/api/v1/transactions/import", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 201
    body = response.json()
    assert body["imported_count"] == 0
    assert body["skipped_count"] == 0


# 📋 POST /api/v1/transactions/import with source_config_id — Generic Bank Import


def should_import_with_source_config_id(api_client):
    """Import using source_config_id instead of legacy source enum."""
    # First create a bank source
    source_response = api_client.post(
        "/api/v1/sources",
        json={"name": "Import Test Bank", "type": "csv_mapping"},
        headers=AUTH_HEADERS,
    )
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]

    # Import with source_config_id
    payload = {
        "source_config_id": source_id,
        "items": [
            {
                "date": "2026-01-15",
                "amount": "123.45",
                "counterparty": "Generic Bank Vendor",
                "description": "Bank import test",
            },
        ],
        "skip_duplicates": True,
    }

    response = api_client.post("/api/v1/transactions/import", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 201
    body = response.json()
    assert body["imported_count"] == 1
    assert body["skipped_count"] == 0

    # Verify transaction has source_config info
    list_response = api_client.get("/api/v1/transactions", headers=AUTH_HEADERS)
    items = list_response.json()["items"]
    assert len(items) >= 1
    matching = [i for i in items if i["counterparty"] == "Generic Bank Vendor"]
    assert len(matching) == 1
    assert matching[0]["source_config_id"] == source_id
    assert matching[0]["source_config_name"] == "Import Test Bank"


def should_use_hash_dedup_with_source_config_id(api_client):
    """Hash-based duplicate detection works with source_config_id imports."""
    # Create source
    source_response = api_client.post(
        "/api/v1/sources",
        json={"name": "Hash Dedup Bank", "type": "csv_mapping"},
        headers=AUTH_HEADERS,
    )
    source_id = source_response.json()["id"]

    items = [
        {
            "date": "2026-02-20",
            "amount": "100.00",
            "counterparty": "Hash Test Vendor",
            "description": "Hash test",
        },
    ]

    # First import
    first = api_client.post(
        "/api/v1/transactions/import",
        json={"source_config_id": source_id, "items": items, "skip_duplicates": True},
        headers=AUTH_HEADERS,
    )
    assert first.json()["imported_count"] == 1

    # Second import - should be skipped due to hash match
    second = api_client.post(
        "/api/v1/transactions/import",
        json={"source_config_id": source_id, "items": items, "skip_duplicates": True},
        headers=AUTH_HEADERS,
    )
    assert second.json()["imported_count"] == 0
    assert second.json()["skipped_count"] == 1


def should_reject_import_without_any_source(api_client):
    """Import without source_config_id should fail with 422 (Pydantic validation)."""
    response = api_client.post(
        "/api/v1/transactions/import",
        json={
            "items": [
                {
                    "date": "2026-01-01",
                    "amount": "50.00",
                    "counterparty": "Test",
                    "description": "No source",
                },
            ],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


def should_reject_import_with_nonexistent_source_config(api_client):
    """Import with non-existent source_config_id should return 404."""
    response = api_client.post(
        "/api/v1/transactions/import",
        json={
            "source_config_id": "00000000-0000-0000-0000-000000000000",
            "items": [
                {
                    "date": "2026-01-01",
                    "amount": "50.00",
                    "counterparty": "Test",
                    "description": "Bad source",
                },
            ],
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404


# 📋 Auth — Require Authentication Headers


def should_reject_request_without_user_headers(api_client):
    """Missing X-User-ID header defaults to empty → 401 Unauthorized."""
    response = api_client.get("/api/v1/transactions")
    assert response.status_code == 401


def should_reject_create_without_user_headers(api_client):
    """Missing X-User-ID header defaults to empty → 401 Unauthorized."""
    payload = {
        "date": "2026-01-20",
        "amount": "50.00",
        "counterparty": "Unauthorized",
        "description": "No auth",
        "source_config_id": "fake-id",
    }
    response = api_client.post("/api/v1/transactions", json=payload)
    assert response.status_code == 401
