"""Tests for the settings router (/api/v1/settings)."""

from tests.conftest import AUTH_HEADERS


class TestPublicSettings:
    """Tests for GET /api/v1/settings/public (unauthenticated)."""

    def should_return_null_company_name_by_default(self, api_client):
        """Public endpoint returns null company_name when not configured."""
        response = api_client.get("/api/v1/settings/public")

        assert response.status_code == 200
        assert response.json() == {"company_name": None}

    def should_not_require_authentication(self, api_client):
        """Public endpoint works without auth headers."""
        response = api_client.get("/api/v1/settings/public")

        assert response.status_code == 200

    def should_return_configured_company_name(self, api_client):
        """Public endpoint returns company_name after it's been set."""
        api_client.patch(
            "/api/v1/settings",
            json={"company_name": "Acme GmbH"},
            headers=AUTH_HEADERS,
        )

        response = api_client.get("/api/v1/settings/public")

        assert response.status_code == 200
        assert response.json() == {"company_name": "Acme GmbH"}


class TestUpdateSettings:
    """Tests for PATCH /api/v1/settings (authenticated)."""

    def should_require_authentication(self, api_client):
        """PATCH without auth headers returns 401 (missing X-User-ID)."""
        response = api_client.patch(
            "/api/v1/settings",
            json={"company_name": "Test"},
        )

        assert response.status_code == 401

    def should_update_company_name(self, api_client):
        """PATCH updates company_name and returns new value."""
        response = api_client.patch(
            "/api/v1/settings",
            json={"company_name": "Example Company GmbH"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["company_name"] == "Example Company GmbH"
        assert data["is_small_business"] is None
        assert data["tax_number"] is None
        assert data["vat_id"] is None
        assert data["legal_form"] is None

    def should_clear_company_name_with_null(self, api_client):
        """PATCH with null clears the company_name."""
        api_client.patch(
            "/api/v1/settings",
            json={"company_name": "Temp Name"},
            headers=AUTH_HEADERS,
        )

        response = api_client.patch(
            "/api/v1/settings",
            json={"company_name": None},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        assert response.json()["company_name"] is None

    def should_reject_unknown_fields(self, api_client):
        """PATCH with extra fields returns 422 (extra=forbid)."""
        response = api_client.patch(
            "/api/v1/settings",
            json={"company_name": "Test", "unknown_field": "value"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 422

    def should_be_idempotent(self, api_client):
        """Multiple PATCH calls with same data produce same result."""
        for _ in range(3):
            response = api_client.patch(
                "/api/v1/settings",
                json={"company_name": "Stable Name"},
                headers=AUTH_HEADERS,
            )

            assert response.status_code == 200
            assert response.json()["company_name"] == "Stable Name"


class TestAuthenticatedSettings:
    """Tests for GET /api/v1/settings (authenticated)."""

    def should_return_new_fields_in_authenticated_settings(self, api_client):
        """Authenticated endpoint returns all fields including tax settings."""
        # Set up some values first
        api_client.patch(
            "/api/v1/settings",
            json={
                "company_name": "Test GmbH",
                "is_small_business": True,
                "tax_number": "123/456/78901",
                "vat_id": "DE123456789",
                "legal_form": "GmbH",
            },
            headers=AUTH_HEADERS,
        )

        response = api_client.get("/api/v1/settings", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["company_name"] == "Test GmbH"
        assert data["is_small_business"] is True
        assert data["tax_number"] == "123/456/78901"
        assert data["vat_id"] == "DE123456789"
        assert data["legal_form"] == "GmbH"

    def should_not_expose_tax_fields_in_public_settings(self, api_client):
        """Public endpoint does NOT return tax-sensitive fields."""
        # Set tax fields
        api_client.patch(
            "/api/v1/settings",
            json={
                "company_name": "Public Company",
                "is_small_business": True,
                "tax_number": "secret/tax/number",
                "vat_id": "DE999999999",
            },
            headers=AUTH_HEADERS,
        )

        # Public endpoint should only have company_name
        response = api_client.get("/api/v1/settings/public")

        assert response.status_code == 200
        data = response.json()
        assert data == {"company_name": "Public Company"}
        # Verify tax fields are NOT exposed
        assert "is_small_business" not in data
        assert "tax_number" not in data
        assert "vat_id" not in data
        assert "legal_form" not in data

    def should_update_is_small_business(self, api_client):
        """PATCH updates is_small_business field."""
        # Set to True
        response = api_client.patch(
            "/api/v1/settings",
            json={"is_small_business": True},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["is_small_business"] is True

        # Set to False
        response = api_client.patch(
            "/api/v1/settings",
            json={"is_small_business": False},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["is_small_business"] is False

        # Clear (set to null)
        response = api_client.patch(
            "/api/v1/settings",
            json={"is_small_business": None},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["is_small_business"] is None

    def should_update_tax_number_and_vat_id(self, api_client):
        """PATCH updates tax_number and vat_id fields."""
        response = api_client.patch(
            "/api/v1/settings",
            json={"tax_number": "329/5832/2840", "vat_id": "DE123456789"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tax_number"] == "329/5832/2840"
        assert data["vat_id"] == "DE123456789"

    def should_update_legal_form(self, api_client):
        """PATCH updates legal_form field."""
        response = api_client.patch(
            "/api/v1/settings",
            json={"legal_form": "Einzelunternehmen"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        assert response.json()["legal_form"] == "Einzelunternehmen"

    def should_validate_vat_id_format(self, api_client):
        """PATCH rejects invalid USt-ID format."""
        # Invalid: wrong prefix
        response = api_client.patch(
            "/api/v1/settings",
            json={"vat_id": "AT123456789"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422

        # Invalid: too few digits
        response = api_client.patch(
            "/api/v1/settings",
            json={"vat_id": "DE12345678"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422

        # Invalid: too many digits
        response = api_client.patch(
            "/api/v1/settings",
            json={"vat_id": "DE1234567890"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422

        # Valid: exactly DE + 9 digits
        response = api_client.patch(
            "/api/v1/settings",
            json={"vat_id": "DE123456789"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200

        # Valid: empty string clears the field
        response = api_client.patch(
            "/api/v1/settings",
            json={"vat_id": ""},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["vat_id"] is None
