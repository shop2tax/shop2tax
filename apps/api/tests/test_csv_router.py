"""Tests for the CSV router (/api/v1/csv).

Tests cover:
1. Generic CSV analysis for bank/marketplace imports (/analyze)
2. Generic CSV parsing with mapping (/parse-generic)
3. File-based upload (/upload-file) and file_id flow
4. OMS enrichment (/enrich)

Note: Hardcoded marketplace parsers (Etsy, Amazon, etc.) were removed.
All CSV imports now use the generic mapping flow.
"""

from tests.conftest import AUTH_HEADERS

# Sample generic bank CSV for analyze/parse-generic tests
GENERIC_BANK_CSV = """Date,Amount,Name,Description
2026-02-20,100.50,Test Corp,Invoice payment
2026-02-21,-50.00,Supplier Inc,Monthly fee
"""

# Sample marketplace CSV with order reference for enrichment tests
MARKETPLACE_CSV = """Date,Amount,Counterparty,Description,OrderNumber
2026-02-20,100.50,etsy@example.com,Order 12345,ORD-12345
2026-02-21,75.25,marketplace@test.com,Order 12346,ORD-12346
"""

# CSV with partial errors (invalid date in second row)
CSV_WITH_ERRORS = """Date,Amount,Name,Description
2026-02-20,100.50,Test Corp,Valid row
invalid-date,50.00,Bad Row,Invalid date format
2026-02-22,75.00,Good Corp,Another valid row
"""


class TestCsvAnalyze:
    """Tests for CSV analysis endpoint (for generic bank imports)."""

    def should_analyze_csv_and_return_options(self, api_client):
        """POST /analyze returns detected options and column info."""
        response = api_client.post(
            "/api/v1/csv/analyze",
            files={"file": ("bank.csv", GENERIC_BANK_CSV.encode(), "text/csv")},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["delimiter"] == ","
        assert len(data["column_headers"]) == 4
        assert "sample_values" in data

    def should_detect_semicolon_delimiter(self, api_client):
        """POST /analyze detects semicolon delimiter."""
        german_csv = "Datum;Betrag;Name;Zweck\n20.02.2026;100,00;Test;Payment\n"
        response = api_client.post(
            "/api/v1/csv/analyze",
            files={"file": ("german.csv", german_csv.encode(), "text/csv")},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["delimiter"] == ";"

    def should_reject_empty_file(self, api_client):
        """POST /analyze with empty file returns error."""
        response = api_client.post(
            "/api/v1/csv/analyze",
            files={"file": ("empty.csv", b"", "text/csv")},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "empty" in data["error"].lower()

    def should_reject_non_csv_file(self, api_client):
        """POST /analyze with unsupported extension returns error."""
        response = api_client.post(
            "/api/v1/csv/analyze",
            files={"file": ("data.pdf", b"some content", "application/pdf")},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False


class TestCsvParseGeneric:
    """Tests for generic CSV parsing with user-defined mapping."""

    def should_parse_with_mapping(self, api_client):
        """POST /parse-generic with mapping returns parsed rows."""
        response = api_client.post(
            "/api/v1/csv/parse-generic",
            files={"file": ("bank.csv", GENERIC_BANK_CSV.encode(), "text/csv")},
            params={
                "delimiter": ",",
                "encoding": "utf-8",
                "has_header": "true",
                "skip_rows": "0",
                "date_format": "%Y-%m-%d",
                "amount_format": "english",
                "column_date": "Date",
                "column_amount": "Amount",
                "column_counterparty": "Name",
                "column_description": "Description",
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["row_count"] == 2
        assert len(data["rows"]) == 2

        # Verify first row
        row = data["rows"][0]
        assert row["date"] == "2026-02-20"
        assert float(row["amount"]) == 100.50
        assert row["counterparty"] == "Test Corp"

    def should_reject_empty_file(self, api_client):
        """POST /parse-generic with empty file returns error."""
        response = api_client.post(
            "/api/v1/csv/parse-generic",
            files={"file": ("empty.csv", b"", "text/csv")},
            params={
                "delimiter": ",",
                "date_format": "%Y-%m-%d",
                "column_date": "Date",
                "column_amount": "Amount",
                "column_counterparty": "Name",
                "column_description": "Desc",
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False


class TestCsvFileUpload:
    """Tests for file-based upload flow (/upload-file, then use file_id)."""

    def should_upload_file_and_return_file_id(self, api_client):
        """POST /upload-file returns a file_id for later use."""
        response = api_client.post(
            "/api/v1/csv/upload-file",
            files={"file": ("bank.csv", GENERIC_BANK_CSV.encode(), "text/csv")},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["file_id"] is not None
        assert data["filename"] == "bank.csv"
        assert data["expires_at"] is not None

    def should_reject_non_csv_upload(self, api_client):
        """POST /upload-file rejects non-CSV/TXT/TSV files."""
        response = api_client.post(
            "/api/v1/csv/upload-file",
            files={"file": ("data.pdf", b"some content", "application/pdf")},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "csv" in data["error"].lower()

    def should_reject_empty_upload(self, api_client):
        """POST /upload-file rejects empty files."""
        response = api_client.post(
            "/api/v1/csv/upload-file",
            files={"file": ("empty.csv", b"", "text/csv")},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "empty" in data["error"].lower()

    def should_analyze_using_file_id(self, api_client):
        """POST /analyze accepts file_id instead of file upload."""
        # First upload the file
        upload_response = api_client.post(
            "/api/v1/csv/upload-file",
            files={"file": ("bank.csv", GENERIC_BANK_CSV.encode(), "text/csv")},
            headers=AUTH_HEADERS,
        )
        file_id = upload_response.json()["file_id"]

        # Then analyze using file_id
        response = api_client.post(
            "/api/v1/csv/analyze",
            data={"file_id": file_id},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["delimiter"] == ","
        assert len(data["column_headers"]) == 4

    def should_parse_generic_using_file_id(self, api_client):
        """POST /parse-generic accepts file_id instead of file upload."""
        # First upload the file
        upload_response = api_client.post(
            "/api/v1/csv/upload-file",
            files={"file": ("bank.csv", GENERIC_BANK_CSV.encode(), "text/csv")},
            headers=AUTH_HEADERS,
        )
        file_id = upload_response.json()["file_id"]

        # Then parse using file_id (file_id is Form, mapping params are Query)
        response = api_client.post(
            "/api/v1/csv/parse-generic",
            data={"file_id": file_id},
            params={
                "delimiter": ",",
                "encoding": "utf-8",
                "has_header": "true",
                "skip_rows": "0",
                "date_format": "%Y-%m-%d",
                "amount_format": "english",
                "column_date": "Date",
                "column_amount": "Amount",
                "column_counterparty": "Name",
                "column_description": "Description",
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["row_count"] == 2

    def should_reject_expired_or_invalid_file_id(self, api_client):
        """POST /analyze with invalid file_id returns error."""
        response = api_client.post(
            "/api/v1/csv/analyze",
            data={"file_id": "nonexistent-file-id"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["error"].lower() or "expired" in data["error"].lower()


class TestCsvParsePartialFailure:
    """Tests for partial failure handling (skip-and-report pattern)."""

    def should_parse_valid_rows_and_report_errors(self, api_client):
        """POST /parse-generic skips invalid rows and reports errors."""
        response = api_client.post(
            "/api/v1/csv/parse-generic",
            files={"file": ("mixed.csv", CSV_WITH_ERRORS.encode(), "text/csv")},
            params={
                "delimiter": ",",
                "encoding": "utf-8",
                "has_header": "true",
                "skip_rows": "0",
                "date_format": "%Y-%m-%d",
                "amount_format": "english",
                "column_date": "Date",
                "column_amount": "Amount",
                "column_counterparty": "Name",
                "column_description": "Description",
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Two valid rows (row 1 and row 3), one error row (row 2)
        assert data["row_count"] == 2
        assert len(data["rows"]) == 2
        # Error for the invalid date row
        assert len(data.get("errors", [])) >= 1

        # Verify the valid rows are correct
        dates = [row["date"] for row in data["rows"]]
        assert "2026-02-20" in dates
        assert "2026-02-22" in dates


class TestCsvEnrich:
    """Tests for OMS enrichment endpoint (/enrich)."""

    def should_enrich_rows_with_oms_match(self, seeded_session, api_client):
        """POST /enrich returns enriched rows when an OMS order matches."""
        from datetime import UTC, datetime
        from decimal import Decimal
        from unittest.mock import AsyncMock, patch
        from uuid import uuid4

        from app.models.oms_store import OmsStore
        from app.services.oms_provider import OmsOrder
        from app.services.providers.billbee import BillbeeProvider

        # Create an OmsStore
        store = OmsStore(
            id=str(uuid4()),
            user_id="test-user-id",
            store_type="etsy",
            label="Test Etsy Store",
            external_shop_id=12345,
            match_strategy="order_number",
        )
        seeded_session.add(store)
        seeded_session.commit()

        # Upload file first
        upload_response = api_client.post(
            "/api/v1/csv/upload-file",
            files={"file": ("marketplace.csv", MARKETPLACE_CSV.encode(), "text/csv")},
            headers=AUTH_HEADERS,
        )
        file_id = upload_response.json()["file_id"]

        # Provider returns a matching OMS order
        mock_order = OmsOrder(
            order_id="999",
            order_number="ORD-12345",
            invoice_number="INV-001",
            invoice_number_prefix="2026-",
            state=3,
            created_at=datetime(2026, 2, 20, tzinfo=UTC),
            total_cost=Decimal("100.50"),
            currency="EUR",
            customer_name="John Doe",
            customer_email="john@example.com",
            shop_id=12345,
            shop_name="Test Shop",
            platform="etsy",
            items=[],
            tags=[],
            paid_amount=Decimal("100.50"),
            is_paid=True,
            paid_at=None,
            tax_rate_1=None,
            tax_rate_2=None,
        )

        with patch.object(
            BillbeeProvider,
            "fetch_orders_cached",
            new_callable=AsyncMock,
            return_value=([mock_order], False, None),
        ):
            response = api_client.post(
                "/api/v1/csv/enrich",
                data={
                    "file_id": file_id,
                    "oms_store_id": store.id,
                },
                params={
                    "delimiter": ",",
                    "encoding": "utf-8",
                    "has_header": "true",
                    "skip_rows": "0",
                    "date_format": "%Y-%m-%d",
                    "amount_format": "english",
                    "column_date": "Date",
                    "column_amount": "Amount",
                    "column_counterparty": "Counterparty",
                    "column_description": "Description",
                    "column_reference": "OrderNumber",
                },
                headers=AUTH_HEADERS,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_rows"] == 2

        # First row should be matched (ORD-12345)
        matched_row = next((r for r in data["rows"] if r["source_reference"] == "ORD-12345"), None)
        assert matched_row is not None
        assert matched_row["match_status"] == "matched"
        assert matched_row["enriched_counterparty"] == "John Doe"
        assert matched_row["enriched_description"] == "2026-INV-001"

        # Second row should be unmatched (ORD-12346)
        unmatched_row = next((r for r in data["rows"] if r["source_reference"] == "ORD-12346"), None)
        assert unmatched_row is not None
        assert unmatched_row["match_status"] == "unmatched"

    def should_return_no_enrichment_without_oms_credentials(self, seeded_session, api_client):
        """POST /enrich returns no_enrichment status when no OMS provider is configured."""
        from unittest.mock import MagicMock, patch
        from uuid import uuid4

        from app.models.oms_store import OmsStore

        # Create an OmsStore
        store = OmsStore(
            id=str(uuid4()),
            user_id="test-user-id",
            store_type="amazon",
            label="Test Amazon Store",
            external_shop_id=67890,
            match_strategy="order_number",
        )
        seeded_session.add(store)
        seeded_session.commit()

        # Upload file first
        upload_response = api_client.post(
            "/api/v1/csv/upload-file",
            files={"file": ("marketplace.csv", MARKETPLACE_CSV.encode(), "text/csv")},
            headers=AUTH_HEADERS,
        )
        file_id = upload_response.json()["file_id"]

        # Mock settings to simulate missing OMS provider credentials → factory returns None
        mock_settings_obj = MagicMock()
        mock_settings_obj.billbee_api_key = ""
        mock_settings_obj.billbee_username = ""
        mock_settings_obj.billbee_password = ""

        with patch("app.config.get_settings", return_value=mock_settings_obj):
            response = api_client.post(
                "/api/v1/csv/enrich",
                data={
                    "file_id": file_id,
                    "oms_store_id": store.id,
                },
                params={
                    "delimiter": ",",
                    "encoding": "utf-8",
                    "has_header": "true",
                    "skip_rows": "0",
                    "date_format": "%Y-%m-%d",
                    "amount_format": "english",
                    "column_date": "Date",
                    "column_amount": "Amount",
                    "column_counterparty": "Counterparty",
                    "column_description": "Description",
                    "column_reference": "OrderNumber",
                },
                headers=AUTH_HEADERS,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "nicht konfiguriert" in data.get("error", "").lower()

        # All rows should have no_enrichment status
        for row in data["rows"]:
            assert row["match_status"] == "no_enrichment"

    def should_reject_invalid_oms_store_id(self, api_client):
        """POST /enrich with invalid store ID returns error."""
        # Upload file first
        upload_response = api_client.post(
            "/api/v1/csv/upload-file",
            files={"file": ("marketplace.csv", MARKETPLACE_CSV.encode(), "text/csv")},
            headers=AUTH_HEADERS,
        )
        file_id = upload_response.json()["file_id"]

        response = api_client.post(
            "/api/v1/csv/enrich",
            data={
                "file_id": file_id,
                "oms_store_id": "nonexistent-store-id",
            },
            params={
                "delimiter": ",",
                "encoding": "utf-8",
                "has_header": "true",
                "skip_rows": "0",
                "date_format": "%Y-%m-%d",
                "amount_format": "english",
                "column_date": "Date",
                "column_amount": "Amount",
                "column_counterparty": "Counterparty",
                "column_description": "Description",
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "nicht gefunden" in data["error"].lower()

    def should_reject_invalid_file_id_for_enrich(self, seeded_session, api_client):
        """POST /enrich with invalid file_id returns error."""
        from uuid import uuid4

        from app.models.oms_store import OmsStore

        # Create an OmsStore
        store = OmsStore(
            id=str(uuid4()),
            user_id="test-user-id",
            store_type="shopify",
            label="Test Shopify Store",
            external_shop_id=11111,
            match_strategy="order_number",
        )
        seeded_session.add(store)
        seeded_session.commit()

        response = api_client.post(
            "/api/v1/csv/enrich",
            data={
                "file_id": "nonexistent-file-id",
                "oms_store_id": store.id,
            },
            params={
                "delimiter": ",",
                "encoding": "utf-8",
                "has_header": "true",
                "skip_rows": "0",
                "date_format": "%Y-%m-%d",
                "amount_format": "english",
                "column_date": "Date",
                "column_amount": "Amount",
                "column_counterparty": "Counterparty",
                "column_description": "Description",
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["error"].lower() or "expired" in data["error"].lower()
