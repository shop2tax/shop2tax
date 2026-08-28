"""📒 Accounts router tests — SKR03 account listing and lookup."""

from tests.conftest import AUTH_HEADERS


def should_list_all_accounts(api_client):
    response = api_client.get("/api/v1/accounts", headers=AUTH_HEADERS)

    assert response.status_code == 200
    accounts = response.json()
    assert len(accounts) == 49


def should_filter_by_category_revenue(api_client):
    response = api_client.get("/api/v1/accounts", headers=AUTH_HEADERS, params={"category": "revenue"})

    assert response.status_code == 200
    accounts = response.json()
    assert len(accounts) > 0
    assert all(account["category"] == "revenue" for account in accounts)


def should_filter_by_category_expense(api_client):
    response = api_client.get("/api/v1/accounts", headers=AUTH_HEADERS, params={"category": "expense"})

    assert response.status_code == 200
    accounts = response.json()
    assert len(accounts) > 0
    assert all(account["category"] == "expense" for account in accounts)


def should_get_account_by_id(api_client):
    response = api_client.get("/api/v1/accounts/8400", headers=AUTH_HEADERS)

    assert response.status_code == 200
    account = response.json()
    assert account["id"] == 8400
    assert "name" in account
    assert "category" in account
    assert "bu_schluessel" in account


def should_return_404_for_unknown_account(api_client):
    response = api_client.get("/api/v1/accounts/9999", headers=AUTH_HEADERS)

    assert response.status_code == 404


def should_include_is_system_in_response(api_client):
    """System accounts (seeded) should have is_system=True."""
    response = api_client.get("/api/v1/accounts/8400", headers=AUTH_HEADERS)

    assert response.status_code == 200
    account = response.json()
    assert account["is_system"] is True


# --- POST /api/v1/accounts ---


def should_create_account(api_client):
    """Create a new user-defined SKR03 account."""
    payload = {
        "id": 4964,
        "name": "Lizenzen und Konzessionen",
        "category": "expense",
        "bu_schluessel": 9,
    }
    response = api_client.post("/api/v1/accounts", headers=AUTH_HEADERS, json=payload)

    assert response.status_code == 201
    account = response.json()
    assert account["id"] == 4964
    assert account["name"] == "Lizenzen und Konzessionen"
    assert account["category"] == "expense"
    assert account["bu_schluessel"] == 9
    assert account["active"] is True
    assert account["is_system"] is False


def should_reject_duplicate_account_id(api_client):
    """Cannot create account with existing ID."""
    # 8400 is a seeded system account
    payload = {
        "id": 8400,
        "name": "Duplicate Account",
        "category": "revenue",
    }
    response = api_client.post("/api/v1/accounts", headers=AUTH_HEADERS, json=payload)

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def should_reject_invalid_account_id_range(api_client):
    """Account ID must be in 1000-8999 range."""
    payload = {
        "id": 999,  # Too low
        "name": "Invalid Account",
        "category": "neutral",
    }
    response = api_client.post("/api/v1/accounts", headers=AUTH_HEADERS, json=payload)

    assert response.status_code == 422  # Pydantic validation error


def should_reject_account_class_0xxx(api_client):
    """Account class 0xxx (Anlagevermögen) is not allowed."""
    payload = {
        "id": 100,  # Class 0 - but also below 1000, will fail range check first
        "name": "Fixed Asset",
        "category": "neutral",
    }
    response = api_client.post("/api/v1/accounts", headers=AUTH_HEADERS, json=payload)

    assert response.status_code == 422


def should_reject_account_class_9xxx(api_client):
    """Account class 9xxx (Vortragskonten) is not allowed."""
    payload = {
        "id": 9000,  # Class 9
        "name": "Vortragskonto",
        "category": "neutral",
    }
    response = api_client.post("/api/v1/accounts", headers=AUTH_HEADERS, json=payload)

    assert response.status_code == 422


def should_reject_invalid_bu_schluessel(api_client):
    """BU-Schlüssel must be 2, 3, 8, or 9 (or None)."""
    payload = {
        "id": 4999,
        "name": "Test Account",
        "category": "expense",
        "bu_schluessel": 5,  # Invalid — only 2, 3, 8, 9 allowed
    }
    response = api_client.post("/api/v1/accounts", headers=AUTH_HEADERS, json=payload)

    assert response.status_code == 422


def should_reject_category_mismatch(api_client):
    """Category must match account class (e.g., 8xxx must be REVENUE)."""
    payload = {
        "id": 8999,  # Class 8 = REVENUE
        "name": "Wrong Category",
        "category": "expense",  # Should be 'revenue'
    }
    response = api_client.post("/api/v1/accounts", headers=AUTH_HEADERS, json=payload)

    assert response.status_code == 422
    assert "requires category" in str(response.json())


def should_set_is_system_false_on_create(api_client):
    """User-created accounts have is_system=False."""
    payload = {
        "id": 4998,
        "name": "User-Created Account",
        "category": "expense",
    }
    response = api_client.post("/api/v1/accounts", headers=AUTH_HEADERS, json=payload)

    assert response.status_code == 201
    assert response.json()["is_system"] is False


# --- PATCH /api/v1/accounts/{account_id} ---


def should_update_account_active_status(api_client):
    """Deactivate an account (soft delete)."""
    # First create a test account
    create_payload = {
        "id": 4997,
        "name": "Account To Deactivate",
        "category": "expense",
    }
    api_client.post("/api/v1/accounts", headers=AUTH_HEADERS, json=create_payload)

    # Now deactivate it
    update_payload = {"active": False}
    response = api_client.patch("/api/v1/accounts/4997", headers=AUTH_HEADERS, json=update_payload)

    assert response.status_code == 200
    assert response.json()["active"] is False


def should_update_account_name(api_client):
    """Update account name."""
    create_payload = {
        "id": 4996,
        "name": "Original Name",
        "category": "expense",
    }
    api_client.post("/api/v1/accounts", headers=AUTH_HEADERS, json=create_payload)

    update_payload = {"name": "Updated Name"}
    response = api_client.patch("/api/v1/accounts/4996", headers=AUTH_HEADERS, json=update_payload)

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Name"


def should_update_account_bu_schluessel(api_client):
    """Update BU-Schlüssel."""
    create_payload = {
        "id": 4995,
        "name": "Test BU Update",
        "category": "expense",
        "bu_schluessel": None,
    }
    api_client.post("/api/v1/accounts", headers=AUTH_HEADERS, json=create_payload)

    update_payload = {"bu_schluessel": 9}
    response = api_client.patch("/api/v1/accounts/4995", headers=AUTH_HEADERS, json=update_payload)

    assert response.status_code == 200
    assert response.json()["bu_schluessel"] == 9


def should_return_404_for_update_unknown_account(api_client):
    """Cannot update non-existent account."""
    update_payload = {"name": "Ghost Account"}
    response = api_client.patch("/api/v1/accounts/9998", headers=AUTH_HEADERS, json=update_payload)

    assert response.status_code == 404
