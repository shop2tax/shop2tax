"""Tests for sources router."""

from tests.conftest import AUTH_HEADERS


class TestListSources:
    """Tests for GET /api/v1/sources."""

    def should_list_system_sources_for_authenticated_user(self, api_client, seeded_session):
        """System sources (marketplace mappings) should be visible to all authenticated users."""
        from app.models.source import SourceType, TransactionSourceConfig

        etsy = TransactionSourceConfig(
            id="system-etsy",
            user_id=None,
            name="Etsy",
            type=SourceType.MARKETPLACE_MAPPING,
        )
        seeded_session.add(etsy)
        seeded_session.commit()

        response = api_client.get("/api/v1/sources", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        etsy_source = next((s for s in data if s["name"] == "Etsy"), None)
        assert etsy_source is not None
        assert etsy_source["type"] == "marketplace_mapping"
        assert etsy_source["is_system"] is True
        assert etsy_source["has_mapping"] is False

    def should_include_user_bank_sources(self, api_client, seeded_session, example_user):
        """User's own CSV mapping sources should be in the list."""
        from app.models.source import SourceType, TransactionSourceConfig

        my_bank = TransactionSourceConfig(
            id="user-bank-1",
            user_id=example_user.id,
            name="My Bank",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(my_bank)
        seeded_session.commit()

        response = api_client.get("/api/v1/sources", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        my_source = next((s for s in data if s["name"] == "My Bank"), None)
        assert my_source is not None
        assert my_source["type"] == "csv_mapping"
        assert my_source["is_system"] is False

    def should_include_all_sources_in_shared_tenant(self, api_client, seeded_session, example_user):
        """Shared tenant: all sources are visible to all users."""
        from app.models.source import SourceType, TransactionSourceConfig
        from app.models.user import User

        other_user = User(
            id="other-user-id",
            provider_id="other-google-id",
            provider_type="google",
            email="other@example.com",
            name="Other User",
        )
        seeded_session.add(other_user)
        seeded_session.flush()

        other_bank = TransactionSourceConfig(
            id="other-user-bank",
            user_id="other-user-id",
            name="Other User Bank",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(other_bank)
        seeded_session.commit()

        response = api_client.get("/api/v1/sources", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        other_source = next((s for s in data if s["name"] == "Other User Bank"), None)
        assert other_source is not None


class TestCreateSource:
    """Tests for POST /api/v1/sources."""

    def should_create_csv_mapping_source(self, api_client, seeded_session):
        """Creating a source should succeed (defaults to CSV_MAPPING type)."""
        response = api_client.post(
            "/api/v1/sources",
            json={"name": "Sparkasse"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Sparkasse"
        assert data["type"] == "csv_mapping"
        assert data["is_system"] is False
        assert "id" in data

    def should_reject_empty_name(self, api_client, seeded_session):
        """Empty name should be rejected."""
        response = api_client.post(
            "/api/v1/sources",
            json={"name": "  "},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 422

    def should_create_source_with_marketplace_config(self, api_client, seeded_session):
        """Source CREATE with source_config persists parser config."""
        response = api_client.post(
            "/api/v1/sources",
            json={
                "name": "Etsy DE",
                "type": "marketplace_mapping",
                "source_config": {"parser": "etsy", "has_ust_id_registered": True},
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["source_config"]["parser"] == "etsy"
        assert data["source_config"]["has_ust_id_registered"] is True

    def should_reject_duplicate_name(self, api_client, seeded_session, example_user):
        """Duplicate name for same user should be rejected."""
        from app.models.source import SourceType, TransactionSourceConfig

        existing = TransactionSourceConfig(
            id="existing-bank",
            user_id=example_user.id,
            name="Sparkasse",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(existing)
        seeded_session.commit()

        response = api_client.post(
            "/api/v1/sources",
            json={"name": "Sparkasse"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]


class TestUpdateSource:
    """Tests for PUT /api/v1/sources/{id}."""

    def should_update_own_source(self, api_client, seeded_session, example_user):
        """User can update their own source."""
        from app.models.source import SourceType, TransactionSourceConfig

        bank = TransactionSourceConfig(
            id="my-bank-to-update",
            user_id=example_user.id,
            name="Old Name",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(bank)
        seeded_session.commit()

        response = api_client.put(
            "/api/v1/sources/my-bank-to-update",
            json={"name": "New Name"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"

    def should_reject_update_system_marketplace_source(self, api_client, seeded_session):
        """System MARKETPLACE_MAPPING sources cannot be updated."""
        from app.models.source import SourceType, TransactionSourceConfig

        system = TransactionSourceConfig(
            id="system-source",
            user_id=None,
            name="System Source",
            type=SourceType.MARKETPLACE_MAPPING,
        )
        seeded_session.add(system)
        seeded_session.commit()

        response = api_client.put(
            "/api/v1/sources/system-source",
            json={"name": "Hacked"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 403

    def should_return_404_for_nonexistent_source(self, api_client, seeded_session):
        """Updating a nonexistent source should return 404."""
        response = api_client.put(
            "/api/v1/sources/nonexistent-id",
            json={"name": "New Name"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 404


class TestDeleteSource:
    """Tests for DELETE /api/v1/sources/{id}."""

    def should_delete_own_source_without_transactions(self, api_client, seeded_session, example_user):
        """User can delete their own source if no transactions linked."""
        from app.models.source import SourceType, TransactionSourceConfig

        bank = TransactionSourceConfig(
            id="bank-to-delete",
            user_id=example_user.id,
            name="Deletable Bank",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(bank)
        seeded_session.commit()

        response = api_client.delete("/api/v1/sources/bank-to-delete", headers=AUTH_HEADERS)

        assert response.status_code == 204

        # Verify it's deleted
        response = api_client.get("/api/v1/sources/bank-to-delete", headers=AUTH_HEADERS)
        assert response.status_code == 404

    def should_reject_delete_system_marketplace_source(self, api_client, seeded_session):
        """System MARKETPLACE_MAPPING sources cannot be deleted."""
        from app.models.source import SourceType, TransactionSourceConfig

        system = TransactionSourceConfig(
            id="system-to-delete",
            user_id=None,
            name="System",
            type=SourceType.MARKETPLACE_MAPPING,
        )
        seeded_session.add(system)
        seeded_session.commit()

        response = api_client.delete("/api/v1/sources/system-to-delete", headers=AUTH_HEADERS)

        assert response.status_code == 403

    def should_reject_delete_source_with_transactions(self, api_client, seeded_session, example_user):
        """Cannot delete source with linked transactions."""
        from app.models.source import SourceType, TransactionSourceConfig
        from app.models.transaction import Transaction

        bank = TransactionSourceConfig(
            id="bank-with-transactions",
            user_id=example_user.id,
            name="Bank With Tx",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(bank)
        seeded_session.flush()

        tx = Transaction(
            id="tx-linked-to-bank",
            user_id=example_user.id,
            date="2026-01-15",
            amount=100,
            counterparty="Test",
            description="Test",
            source_config_id=bank.id,
        )
        seeded_session.add(tx)
        seeded_session.commit()

        response = api_client.delete("/api/v1/sources/bank-with-transactions", headers=AUTH_HEADERS)

        assert response.status_code == 409
        assert "linked transactions" in response.json()["detail"]
