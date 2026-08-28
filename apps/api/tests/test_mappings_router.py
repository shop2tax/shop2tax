"""Tests for mappings router."""

from tests.conftest import AUTH_HEADERS


class TestListMappings:
    """Tests for GET /api/v1/mappings."""

    def should_list_user_mappings(self, api_client, seeded_session, example_user):
        """User's mapping profiles should be listed."""
        from app.models.source import CsvMappingProfile, SourceType, TransactionSourceConfig

        # Create a source and mapping
        source = TransactionSourceConfig(
            id="source-for-mapping",
            user_id=example_user.id,
            name="My Bank",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(source)
        seeded_session.flush()

        mapping = CsvMappingProfile(
            id="mapping-1",
            user_id=example_user.id,
            source_id=source.id,
            name="DKB Mapping",
            delimiter=";",
            encoding="utf-8",
            has_header=True,
            skip_rows=4,
            date_format="dd.MM.yyyy",
            amount_format="german",
            column_date="Buchungstag",
            column_amount="Betrag (EUR)",
            column_counterparty="Auftraggeber/Empfänger",
            column_description="Verwendungszweck",
        )
        seeded_session.add(mapping)
        seeded_session.commit()

        response = api_client.get("/api/v1/mappings", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "DKB Mapping"
        assert data[0]["delimiter"] == ";"
        assert data[0]["source_name"] == "My Bank"

    def should_list_all_mappings_in_shared_tenant(self, api_client, seeded_session, example_user):
        """Shared tenant: all mappings are visible to all users."""
        from app.models.source import CsvMappingProfile, SourceType, TransactionSourceConfig
        from app.models.user import User

        # Create another user first
        other_user = User(
            id="other-user",
            provider_id="other-google-id",
            provider_type="google",
            email="other@example.com",
            name="Other User",
        )
        seeded_session.add(other_user)
        seeded_session.flush()

        source = TransactionSourceConfig(
            id="other-user-source",
            user_id="other-user",
            name="Other Bank",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(source)
        seeded_session.flush()

        mapping = CsvMappingProfile(
            id="other-mapping",
            user_id="other-user",
            source_id=source.id,
            column_date="Date",
            column_amount="Amount",
            column_counterparty="Name",
            column_description="Memo",
        )
        seeded_session.add(mapping)
        seeded_session.commit()

        response = api_client.get("/api/v1/mappings", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1


class TestGetMappingBySource:
    """Tests for GET /api/v1/mappings/by-source/{source_id}."""

    def should_get_mapping_for_source(self, api_client, seeded_session, example_user):
        """Get mapping for a specific source."""
        from app.models.source import CsvMappingProfile, SourceType, TransactionSourceConfig

        source = TransactionSourceConfig(
            id="source-with-mapping",
            user_id=example_user.id,
            name="My Bank",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(source)
        seeded_session.flush()

        mapping = CsvMappingProfile(
            id="mapping-for-source",
            user_id=example_user.id,
            source_id=source.id,
            column_date="Date",
            column_amount="Amount",
            column_counterparty="Name",
            column_description="Memo",
        )
        seeded_session.add(mapping)
        seeded_session.commit()

        response = api_client.get("/api/v1/mappings/by-source/source-with-mapping", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["source_id"] == "source-with-mapping"

    def should_return_null_for_source_without_mapping(self, api_client, seeded_session, example_user):
        """Return 200 with null body when source exists but has no mapping."""
        from app.models.source import SourceType, TransactionSourceConfig

        source = TransactionSourceConfig(
            id="source-no-mapping",
            user_id=example_user.id,
            name="Bank Without Mapping",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(source)
        seeded_session.commit()

        response = api_client.get("/api/v1/mappings/by-source/source-no-mapping", headers=AUTH_HEADERS)

        assert response.status_code == 200
        assert response.json() is None

    def should_return_404_for_nonexistent_source(self, api_client, seeded_session):
        """Return 404 for nonexistent source."""
        response = api_client.get("/api/v1/mappings/by-source/nonexistent", headers=AUTH_HEADERS)

        assert response.status_code == 404


class TestCreateOrUpdateMapping:
    """Tests for POST /api/v1/mappings."""

    def should_create_mapping(self, api_client, seeded_session, example_user):
        """Create a mapping with amount column."""
        from app.models.source import SourceType, TransactionSourceConfig

        source = TransactionSourceConfig(
            id="source-for-new-mapping",
            user_id=example_user.id,
            name="New Bank",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(source)
        seeded_session.commit()

        response = api_client.post(
            "/api/v1/mappings",
            json={
                "source_id": "source-for-new-mapping",
                "name": "My Mapping",
                "delimiter": ",",
                "encoding": "utf-8",
                "has_header": True,
                "skip_rows": 0,
                "date_format": "YYYY-MM-DD",
                "amount_format": "english",
                "column_date": "Date",
                "column_amount": "Amount",
                "column_counterparty": "Payee",
                "column_description": "Memo",
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "My Mapping"
        assert data["column_amount"] == "Amount"

    def should_update_existing_mapping(self, api_client, seeded_session, example_user):
        """Posting to same source updates existing mapping (upsert)."""
        from app.models.source import CsvMappingProfile, SourceType, TransactionSourceConfig

        source = TransactionSourceConfig(
            id="source-for-upsert",
            user_id=example_user.id,
            name="Upsert Bank",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(source)
        seeded_session.flush()

        existing = CsvMappingProfile(
            id="existing-mapping",
            user_id=example_user.id,
            source_id=source.id,
            column_date="OldDate",
            column_amount="OldAmount",
            column_counterparty="OldName",
            column_description="OldMemo",
        )
        seeded_session.add(existing)
        seeded_session.commit()

        # Update via POST (upsert)
        response = api_client.post(
            "/api/v1/mappings",
            json={
                "source_id": "source-for-upsert",
                "name": "Updated Mapping",
                "column_date": "NewDate",
                "column_amount": "NewAmount",
                "column_counterparty": "NewName",
                "column_description": "NewMemo",
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Updated Mapping"
        assert data["column_date"] == "NewDate"

    def should_accept_mapping_with_only_reference(self, api_client, seeded_session, example_user):
        """Marketplace mapping with only reference column should be accepted."""
        from app.models.source import SourceType, TransactionSourceConfig

        source = TransactionSourceConfig(
            id="source-for-ref-only",
            user_id=example_user.id,
            name="Marketplace Ref Only",
            type=SourceType.MARKETPLACE_MAPPING,
        )
        seeded_session.add(source)
        seeded_session.commit()

        response = api_client.post(
            "/api/v1/mappings",
            json={
                "source_id": "source-for-ref-only",
                "column_reference": "Info",
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["column_reference"] == "Info"
        assert data["column_date"] is None
        assert data["column_amount"] is None


class TestDeleteMapping:
    """Tests for DELETE /api/v1/mappings/{id}."""

    def should_delete_own_mapping(self, api_client, seeded_session, example_user):
        """User can delete their own mapping."""
        from app.models.source import CsvMappingProfile, SourceType, TransactionSourceConfig

        source = TransactionSourceConfig(
            id="source-for-delete",
            user_id=example_user.id,
            name="Delete Bank",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(source)
        seeded_session.flush()

        mapping = CsvMappingProfile(
            id="mapping-to-delete",
            user_id=example_user.id,
            source_id=source.id,
            column_date="Date",
            column_amount="Amount",
            column_counterparty="Name",
            column_description="Memo",
        )
        seeded_session.add(mapping)
        seeded_session.commit()

        response = api_client.delete("/api/v1/mappings/mapping-to-delete", headers=AUTH_HEADERS)

        assert response.status_code == 204

    def should_delete_any_mapping_in_shared_tenant(self, api_client, seeded_session, example_user):
        """Shared tenant: any user can delete any mapping."""
        from app.models.source import CsvMappingProfile, SourceType, TransactionSourceConfig
        from app.models.user import User

        other_user = User(
            id="other-user-delete",
            provider_id="other-google-id-delete",
            provider_type="google",
            email="other-delete@example.com",
            name="Other User Delete",
        )
        seeded_session.add(other_user)
        seeded_session.flush()

        source = TransactionSourceConfig(
            id="other-source",
            user_id="other-user-delete",
            name="Other Bank",
            type=SourceType.CSV_MAPPING,
        )
        seeded_session.add(source)
        seeded_session.flush()

        mapping = CsvMappingProfile(
            id="other-mapping-delete",
            user_id="other-user-delete",
            source_id=source.id,
            column_date="Date",
            column_amount="Amount",
            column_counterparty="Name",
            column_description="Memo",
        )
        seeded_session.add(mapping)
        seeded_session.commit()

        response = api_client.delete("/api/v1/mappings/other-mapping-delete", headers=AUTH_HEADERS)

        assert response.status_code == 204
