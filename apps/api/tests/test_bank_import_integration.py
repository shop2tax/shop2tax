"""Integration tests for the full bank CSV import flow.

Tests cover the complete workflow:
1. Create a bank source
2. Upload/analyze CSV to get column info
3. Parse with user-defined column mapping
4. Import transactions with source_config_id
5. Verify hash-based duplicate detection
"""

from decimal import Decimal

from tests.conftest import AUTH_HEADERS

# Sample German bank CSV (DKB-style with semicolons and german numbers)
GERMAN_BANK_CSV = """Buchungsdatum;Betrag;Empfänger;Verwendungszweck
20.02.2026;100,50;Test Corp;Rechnungszahlung
21.02.2026;-50,00;Lieferant GmbH;Monatliche Gebühr
22.02.2026;1.234,56;Big Customer;Großbestellung
"""

# Sample English bank CSV (comma-separated, english numbers)
ENGLISH_BANK_CSV = """Date,Amount,Recipient,Description
2026-02-20,100.50,Test Corp,Invoice payment
2026-02-21,-50.00,Supplier Inc,Monthly fee
"""


class TestBankImportIntegration:
    """Full integration tests for bank CSV import workflow."""

    def should_complete_full_import_flow_german_csv(self, api_client, database_session):
        """Complete workflow: create source → analyze → parse → import (German CSV)."""
        # Step 1: Create a bank source
        source_response = api_client.post(
            "/api/v1/sources",
            json={"name": "Test Bank", "type": "csv_mapping"},
            headers=AUTH_HEADERS,
        )
        assert source_response.status_code == 201
        source = source_response.json()
        source_id = source["id"]
        assert source["name"] == "Test Bank"
        assert source["type"] == "csv_mapping"

        # Step 2: Analyze the CSV to get column headers and detected options
        analyze_response = api_client.post(
            "/api/v1/csv/analyze",
            files={"file": ("bank.csv", GERMAN_BANK_CSV.encode("utf-8"), "text/csv")},
            headers=AUTH_HEADERS,
        )
        assert analyze_response.status_code == 200
        analyze_data = analyze_response.json()
        assert analyze_data["success"] is True
        assert analyze_data["delimiter"] == ";"
        assert "Buchungsdatum" in analyze_data["column_headers"]
        assert "Betrag" in analyze_data["column_headers"]

        # Step 3: Parse with user-defined column mapping
        parse_response = api_client.post(
            "/api/v1/csv/parse-generic",
            files={"file": ("bank.csv", GERMAN_BANK_CSV.encode("utf-8"), "text/csv")},
            params={
                "delimiter": ";",
                "encoding": "utf-8",
                "has_header": "true",
                "skip_rows": "0",
                "date_format": "%d.%m.%Y",
                "amount_format": "german",
                "column_date": "Buchungsdatum",
                "column_amount": "Betrag",
                "column_counterparty": "Empfänger",
                "column_description": "Verwendungszweck",
            },
            headers=AUTH_HEADERS,
        )
        assert parse_response.status_code == 200
        parse_data = parse_response.json()
        assert parse_data["success"] is True
        assert parse_data["row_count"] == 3

        # Verify parsed amounts (German format → Decimal)
        rows = parse_data["rows"]
        assert rows[0]["date"] == "2026-02-20"
        assert Decimal(rows[0]["amount"]) == Decimal("100.50")
        assert rows[0]["counterparty"] == "Test Corp"

        assert rows[1]["date"] == "2026-02-21"
        assert Decimal(rows[1]["amount"]) == Decimal("-50.00")

        assert rows[2]["date"] == "2026-02-22"
        assert Decimal(rows[2]["amount"]) == Decimal("1234.56")

        # Step 4: Import transactions with source_config_id
        import_items = [
            {
                "date": row["date"],
                "amount": row["amount"],
                "counterparty": row["counterparty"],
                "description": row["description"],
            }
            for row in rows
        ]

        import_response = api_client.post(
            "/api/v1/transactions/import",
            json={
                "source_config_id": source_id,
                "items": import_items,
                "skip_duplicates": True,
            },
            headers=AUTH_HEADERS,
        )
        assert import_response.status_code == 201
        import_data = import_response.json()
        assert import_data["imported_count"] == 3
        assert import_data["skipped_count"] == 0
        assert import_data["error_count"] == 0

        # Step 5: Verify transactions exist with correct source_config
        list_response = api_client.get("/api/v1/transactions", headers=AUTH_HEADERS)
        assert list_response.status_code == 200
        transactions = list_response.json()["items"]
        assert len(transactions) == 3

        # Check that transactions have source_config_id set
        for txn in transactions:
            assert txn["source_config_id"] == source_id
            assert txn["source_config_name"] == "Test Bank"

    def should_complete_full_import_flow_english_csv(self, api_client, database_session):
        """Complete workflow with English CSV format."""
        # Step 1: Create a bank source
        source_response = api_client.post(
            "/api/v1/sources",
            json={"name": "English Bank", "type": "csv_mapping"},
            headers=AUTH_HEADERS,
        )
        assert source_response.status_code == 201
        source_id = source_response.json()["id"]

        # Step 2: Parse with English format
        parse_response = api_client.post(
            "/api/v1/csv/parse-generic",
            files={"file": ("bank.csv", ENGLISH_BANK_CSV.encode("utf-8"), "text/csv")},
            params={
                "delimiter": ",",
                "encoding": "utf-8",
                "has_header": "true",
                "skip_rows": "0",
                "date_format": "%Y-%m-%d",
                "amount_format": "english",
                "column_date": "Date",
                "column_amount": "Amount",
                "column_counterparty": "Recipient",
                "column_description": "Description",
            },
            headers=AUTH_HEADERS,
        )
        assert parse_response.status_code == 200
        parse_data = parse_response.json()
        assert parse_data["success"] is True
        assert parse_data["row_count"] == 2

        # Step 3: Import
        import_items = [
            {
                "date": row["date"],
                "amount": row["amount"],
                "counterparty": row["counterparty"],
                "description": row["description"],
            }
            for row in parse_data["rows"]
        ]

        import_response = api_client.post(
            "/api/v1/transactions/import",
            json={
                "source_config_id": source_id,
                "items": import_items,
                "skip_duplicates": True,
            },
            headers=AUTH_HEADERS,
        )
        assert import_response.status_code == 201
        assert import_response.json()["imported_count"] == 2

    def should_detect_duplicates_with_hash(self, api_client, database_session):
        """Hash-based duplicate detection should skip already imported rows."""
        # Create source
        source_response = api_client.post(
            "/api/v1/sources",
            json={"name": "Dedup Test Bank", "type": "csv_mapping"},
            headers=AUTH_HEADERS,
        )
        source_id = source_response.json()["id"]

        # First import
        import_items = [
            {
                "date": "2026-02-20",
                "amount": "100.50",
                "counterparty": "Test Corp",
                "description": "Payment",
            },
        ]

        first_import = api_client.post(
            "/api/v1/transactions/import",
            json={
                "source_config_id": source_id,
                "items": import_items,
                "skip_duplicates": True,
            },
            headers=AUTH_HEADERS,
        )
        assert first_import.status_code == 201
        assert first_import.json()["imported_count"] == 1
        assert first_import.json()["skipped_count"] == 0

        # Second import with same data - should be skipped
        second_import = api_client.post(
            "/api/v1/transactions/import",
            json={
                "source_config_id": source_id,
                "items": import_items,
                "skip_duplicates": True,
            },
            headers=AUTH_HEADERS,
        )
        assert second_import.status_code == 201
        assert second_import.json()["imported_count"] == 0
        assert second_import.json()["skipped_count"] == 1

        # Verify only one transaction exists
        list_response = api_client.get("/api/v1/transactions", headers=AUTH_HEADERS)
        assert list_response.json()["total"] == 1

    def should_allow_duplicates_when_disabled(self, api_client, database_session):
        """When skip_duplicates=False, import should not skip duplicates."""
        # Create source
        source_response = api_client.post(
            "/api/v1/sources",
            json={"name": "Allow Dups Bank", "type": "csv_mapping"},
            headers=AUTH_HEADERS,
        )
        source_id = source_response.json()["id"]

        import_items = [
            {
                "date": "2026-02-20",
                "amount": "100.50",
                "counterparty": "Test Corp",
                "description": "Payment",
            },
        ]

        # First import
        api_client.post(
            "/api/v1/transactions/import",
            json={
                "source_config_id": source_id,
                "items": import_items,
                "skip_duplicates": False,
            },
            headers=AUTH_HEADERS,
        )

        # Second import with skip_duplicates=False
        second_import = api_client.post(
            "/api/v1/transactions/import",
            json={
                "source_config_id": source_id,
                "items": import_items,
                "skip_duplicates": False,
            },
            headers=AUTH_HEADERS,
        )
        assert second_import.status_code == 201
        assert second_import.json()["imported_count"] == 1

        # Should have 2 transactions now
        list_response = api_client.get("/api/v1/transactions", headers=AUTH_HEADERS)
        assert list_response.json()["total"] == 2

    def should_reject_import_without_source_identifier(self, api_client):
        """Import without source or source_config_id should fail."""
        import_response = api_client.post(
            "/api/v1/transactions/import",
            json={
                "items": [
                    {
                        "date": "2026-02-20",
                        "amount": "100.00",
                        "counterparty": "Test",
                        "description": "Payment",
                    }
                ],
            },
            headers=AUTH_HEADERS,
        )
        assert import_response.status_code == 422
        # Pydantic returns validation error for missing source_config_id

    def should_reject_import_with_invalid_source_config_id(self, api_client):
        """Import with non-existent source_config_id should fail."""
        import_response = api_client.post(
            "/api/v1/transactions/import",
            json={
                "source_config_id": "00000000-0000-0000-0000-000000000000",
                "items": [
                    {
                        "date": "2026-02-20",
                        "amount": "100.00",
                        "counterparty": "Test",
                        "description": "Payment",
                    }
                ],
            },
            headers=AUTH_HEADERS,
        )
        assert import_response.status_code == 404
        assert "source config" in import_response.json()["detail"].lower()


class TestMappingProfileIntegration:
    """Tests for saving and reusing mapping profiles."""

    def should_save_and_reuse_mapping_profile(self, api_client, database_session):
        """Save a mapping profile and reuse it for subsequent imports."""
        # Create source
        source_response = api_client.post(
            "/api/v1/sources",
            json={"name": "Profile Test Bank", "type": "csv_mapping"},
            headers=AUTH_HEADERS,
        )
        source_id = source_response.json()["id"]

        # Create a mapping profile
        mapping_response = api_client.post(
            "/api/v1/mappings",
            json={
                "source_id": source_id,
                "name": "My DKB Mapping",
                "delimiter": ";",
                "encoding": "utf-8",
                "has_header": True,
                "skip_rows": 0,
                "date_format": "%d.%m.%Y",
                "amount_format": "german",
                "column_date": "Buchungsdatum",
                "column_amount": "Betrag",
                "column_counterparty": "Empfänger",
                "column_description": "Verwendungszweck",
            },
            headers=AUTH_HEADERS,
        )
        assert mapping_response.status_code == 201
        mapping = mapping_response.json()
        assert mapping["name"] == "My DKB Mapping"
        assert mapping["delimiter"] == ";"

        # Get mapping for the source
        get_mapping_response = api_client.get(
            f"/api/v1/mappings/by-source/{source_id}",
            headers=AUTH_HEADERS,
        )
        assert get_mapping_response.status_code == 200
        saved_mapping = get_mapping_response.json()
        assert saved_mapping["column_date"] == "Buchungsdatum"
        assert saved_mapping["amount_format"] == "german"

    def should_list_user_mappings(self, api_client, database_session):
        """List all mapping profiles for current user."""
        # Create two sources with mappings
        for i in range(2):
            source_response = api_client.post(
                "/api/v1/sources",
                json={"name": f"Bank {i + 1}", "type": "csv_mapping"},
                headers=AUTH_HEADERS,
            )
            source_id = source_response.json()["id"]

            api_client.post(
                "/api/v1/mappings",
                json={
                    "source_id": source_id,
                    "name": f"Mapping {i + 1}",
                    "delimiter": ",",
                    "encoding": "utf-8",
                    "has_header": True,
                    "skip_rows": 0,
                    "date_format": "%Y-%m-%d",
                    "amount_format": "english",
                    "column_date": "Date",
                    "column_amount": "Amount",
                    "column_counterparty": "Name",
                    "column_description": "Desc",
                },
                headers=AUTH_HEADERS,
            )

        # List mappings
        list_response = api_client.get("/api/v1/mappings", headers=AUTH_HEADERS)
        assert list_response.status_code == 200
        mappings = list_response.json()
        assert len(mappings) >= 2
