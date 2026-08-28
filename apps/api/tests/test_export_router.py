"""Tests for the export router (/api/v1/export)."""

from datetime import date
from decimal import Decimal

from tests.conftest import AUTH_HEADERS, _create_example_transaction

DATEV_CONFIG = {
    "beraternummer": "1234567",
    "mandantennummer": "12345",
    "wirtschaftsjahr_beginn": "2026-01-01",
}

EXPORT_REQUEST = {
    "config": DATEV_CONFIG,
    "date_from": "2026-01-01",
    "date_to": "2026-12-31",
    "include_unreconciled": False,
}


class TestDatevSettings:
    """Tests for DATEV settings endpoints."""

    def should_return_null_settings_by_default(self, api_client):
        """GET /datev/settings returns null for a user without stored config."""
        response = api_client.get("/api/v1/export/datev/settings", headers=AUTH_HEADERS)

        assert response.status_code == 200
        assert response.json() is None

    def should_store_and_retrieve_datev_settings(self, api_client):
        """PUT then GET settings roundtrip preserves all fields."""
        # Store settings
        put_response = api_client.put(
            "/api/v1/export/datev/settings",
            json=DATEV_CONFIG,
            headers=AUTH_HEADERS,
        )
        assert put_response.status_code == 200
        stored = put_response.json()
        assert stored["beraternummer"] == "1234567"
        assert stored["mandantennummer"] == "12345"
        assert stored["wirtschaftsjahr_beginn"] == "2026-01-01"

        # Retrieve settings
        get_response = api_client.get("/api/v1/export/datev/settings", headers=AUTH_HEADERS)
        assert get_response.status_code == 200
        retrieved = get_response.json()
        assert retrieved["beraternummer"] == "1234567"
        assert retrieved["mandantennummer"] == "12345"
        assert retrieved["wirtschaftsjahr_beginn"] == "2026-01-01"


class TestDatevExportRouter:
    """Tests for DATEV export generation endpoints."""

    def should_generate_datev_export(self, api_client, database_session):
        """POST /datev with reconciled transactions returns export rows."""
        from uuid import uuid4

        from app.models.receipt import Receipt, ReceiptType
        from app.models.receipt_line_item import ReceiptLineItem
        from app.models.receipt_transaction_link import ReceiptTransactionLink

        transaction = _create_example_transaction(
            database_session,
            amount=Decimal("119.00"),
        )
        receipt = Receipt(
            id=str(uuid4()),
            user_id="test-user-id",
            type=ReceiptType.EXPENSE,
            receipt_number="R-001",
            date=date(2026, 1, 15),
            counterparty="Supplier",
        )
        database_session.add(receipt)
        database_session.flush()
        line_item = ReceiptLineItem(
            id=str(uuid4()),
            receipt_id=receipt.id,
            position=1,
            description="Office supplies",
            amount=Decimal("119.00"),
            skr03_account_id=8400,
        )
        database_session.add(line_item)
        link = ReceiptTransactionLink(
            receipt_id=receipt.id,
            transaction_id=transaction.id,
        )
        database_session.add(link)
        database_session.commit()

        response = api_client.post("/api/v1/export/datev", json=EXPORT_REQUEST, headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["transaction_count"] >= 1
        assert len(data["rows"]) >= 1
        assert len(data["header"]) >= 1
        assert "EXTF" in data["csv_content"]

    def should_generate_empty_export_without_transactions(self, api_client, database_session):
        """POST /datev returns 0 rows when no transactions exist."""
        database_session.commit()

        response = api_client.post("/api/v1/export/datev", json=EXPORT_REQUEST, headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["transaction_count"] == 0
        assert len(data["rows"]) == 0

    def should_download_datev_csv(self, api_client, database_session):
        """POST /datev/download returns text/csv with Content-Disposition header."""
        from uuid import uuid4

        from app.models.receipt import Receipt, ReceiptType
        from app.models.receipt_line_item import ReceiptLineItem
        from app.models.receipt_transaction_link import ReceiptTransactionLink

        transaction = _create_example_transaction(
            database_session,
            amount=Decimal("119.00"),
        )
        receipt = Receipt(
            id=str(uuid4()),
            user_id="test-user-id",
            type=ReceiptType.EXPENSE,
            receipt_number="R-002",
            date=date(2026, 1, 15),
            counterparty="Supplier",
        )
        database_session.add(receipt)
        database_session.flush()
        line_item = ReceiptLineItem(
            id=str(uuid4()),
            receipt_id=receipt.id,
            position=1,
            description="Office supplies",
            amount=Decimal("119.00"),
            skr03_account_id=8400,
        )
        database_session.add(line_item)
        link = ReceiptTransactionLink(
            receipt_id=receipt.id,
            transaction_id=transaction.id,
        )
        database_session.add(link)
        database_session.commit()

        response = api_client.post("/api/v1/export/datev/download", json=EXPORT_REQUEST, headers=AUTH_HEADERS)

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "Content-Disposition" in response.headers
        assert "attachment" in response.headers["Content-Disposition"]
        assert "DATEV_Buchungsstapel" in response.headers["Content-Disposition"]
        assert "EXTF" in response.text

    def should_validate_export(self, api_client, database_session):
        """POST /datev/validate returns valid=true for well-formed export."""
        from uuid import uuid4

        from app.models.receipt import Receipt, ReceiptType
        from app.models.receipt_line_item import ReceiptLineItem
        from app.models.receipt_transaction_link import ReceiptTransactionLink

        transaction = _create_example_transaction(
            database_session,
            amount=Decimal("119.00"),
        )
        receipt = Receipt(
            id=str(uuid4()),
            user_id="test-user-id",
            type=ReceiptType.EXPENSE,
            receipt_number="R-003",
            date=date(2026, 1, 15),
            counterparty="Supplier",
        )
        database_session.add(receipt)
        database_session.flush()
        line_item = ReceiptLineItem(
            id=str(uuid4()),
            receipt_id=receipt.id,
            position=1,
            description="Office supplies",
            amount=Decimal("119.00"),
            skr03_account_id=8400,
        )
        database_session.add(line_item)
        link = ReceiptTransactionLink(
            receipt_id=receipt.id,
            transaction_id=transaction.id,
        )
        database_session.add(link)
        database_session.commit()

        response = api_client.post("/api/v1/export/datev/validate", json=EXPORT_REQUEST, headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert len(data["errors"]) == 0


class TestDatevPreview:
    """Tests for DATEV preview endpoint."""

    def should_preview_datev_export(self, api_client, database_session):
        """GET /datev/preview with query params returns export response."""
        from uuid import uuid4

        from app.models.receipt import Receipt, ReceiptType
        from app.models.receipt_line_item import ReceiptLineItem
        from app.models.receipt_transaction_link import ReceiptTransactionLink

        transaction = _create_example_transaction(
            database_session,
            amount=Decimal("119.00"),
        )
        receipt = Receipt(
            id=str(uuid4()),
            user_id="test-user-id",
            type=ReceiptType.EXPENSE,
            receipt_number="R-004",
            date=date(2026, 1, 15),
            counterparty="Supplier",
        )
        database_session.add(receipt)
        database_session.flush()
        line_item = ReceiptLineItem(
            id=str(uuid4()),
            receipt_id=receipt.id,
            position=1,
            description="Office supplies",
            amount=Decimal("119.00"),
            skr03_account_id=8400,
        )
        database_session.add(line_item)
        link = ReceiptTransactionLink(
            receipt_id=receipt.id,
            transaction_id=transaction.id,
        )
        database_session.add(link)
        database_session.commit()

        response = api_client.get(
            "/api/v1/export/datev/preview",
            params={
                "beraternummer": "1234567",
                "mandantennummer": "12345",
                "wirtschaftsjahr_beginn": "2026-01-01",
                "date_from": "2026-01-01",
                "date_to": "2026-12-31",
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["transaction_count"] >= 1
        assert len(data["rows"]) >= 1
        assert "EXTF" in data["csv_content"]

    def should_preview_empty_export_without_transactions(self, api_client, database_session):
        """GET /datev/preview returns 0 rows when no transactions match."""
        database_session.commit()

        response = api_client.get(
            "/api/v1/export/datev/preview",
            params={
                "beraternummer": "1234567",
                "mandantennummer": "12345",
                "wirtschaftsjahr_beginn": "2026-01-01",
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["transaction_count"] == 0
        assert data["rows"] == []


class TestExportHistory:
    """Tests for export history endpoint."""

    def should_list_empty_export_history(self, api_client):
        """GET /history returns empty list for a user with no exports."""
        response = api_client.get("/api/v1/export/history", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def should_filter_export_history_by_type(self, api_client, database_session):
        """GET /history?export_type=datev returns only datev exports."""
        from datetime import UTC, datetime

        from app.models.export_log import ExportLog

        # Create two export logs with different types
        datev_log = ExportLog(
            user_id="test-user-id",
            export_type="datev",
            transaction_count=5,
            line_item_count=5,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 6, 30),
            beraternummer="1234567",
            mandantennummer="12345",
            filename="DATEV_export.csv",
            created_at=datetime.now(UTC),
        )
        other_log = ExportLog(
            user_id="test-user-id",
            export_type="other",
            transaction_count=3,
            line_item_count=3,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 3, 31),
            beraternummer="1234567",
            mandantennummer="12345",
            filename="other_export.csv",
            created_at=datetime.now(UTC),
        )
        database_session.add(datev_log)
        database_session.add(other_log)
        database_session.commit()

        response = api_client.get(
            "/api/v1/export/history",
            params={"export_type": "datev"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["export_type"] == "datev"

    def should_return_empty_for_unknown_export_type(self, api_client, database_session):
        """GET /history?export_type=nonexistent returns empty list."""
        from datetime import UTC, datetime

        from app.models.export_log import ExportLog

        # Create a datev log, then filter for a type that doesn't exist
        log = ExportLog(
            user_id="test-user-id",
            export_type="datev",
            transaction_count=2,
            line_item_count=2,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 3, 31),
            beraternummer="1234567",
            mandantennummer="12345",
            filename="export.csv",
            created_at=datetime.now(UTC),
        )
        database_session.add(log)
        database_session.commit()

        response = api_client.get(
            "/api/v1/export/history",
            params={"export_type": "nonexistent"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


ZIP_EXPORT_REQUEST = {
    "config": DATEV_CONFIG,
    "date_from": "2026-01-01",
    "date_to": "2026-12-31",
    "include_receipts": True,
    "finalized_only": False,
    "document_types": None,
}


class TestDatevZipExport:
    """Tests for DATEV ZIP export with Belegbilder."""

    def should_download_zip_with_csv_only_when_no_receipts_have_files(self, api_client, database_session):
        """POST /datev/download/zip returns ZIP containing only CSV if no receipts have files."""
        import io
        import zipfile
        from uuid import uuid4

        from app.models.receipt import Receipt, ReceiptType
        from app.models.receipt_line_item import ReceiptLineItem
        from app.models.receipt_transaction_link import ReceiptTransactionLink

        # Create transaction with receipt WITHOUT file
        transaction = _create_example_transaction(
            database_session,
            amount=Decimal("100.00"),
        )
        receipt = Receipt(
            id=str(uuid4()),
            user_id="test-user-id",
            type=ReceiptType.REVENUE,
            receipt_number="INV-001",
            date=date(2026, 1, 15),
            counterparty="Customer",
            # file_storage_id is None
        )
        database_session.add(receipt)
        database_session.flush()
        line_item = ReceiptLineItem(
            id=str(uuid4()),
            receipt_id=receipt.id,
            position=1,
            description="Service",
            amount=Decimal("100.00"),
            skr03_account_id=8400,
        )
        database_session.add(line_item)
        link = ReceiptTransactionLink(
            receipt_id=receipt.id,
            transaction_id=transaction.id,
        )
        database_session.add(link)
        database_session.commit()

        response = api_client.post("/api/v1/export/datev/download/zip", json=ZIP_EXPORT_REQUEST, headers=AUTH_HEADERS)

        assert response.status_code == 200
        assert "application/zip" in response.headers["content-type"]
        assert "Content-Disposition" in response.headers
        assert "DATEV_Export" in response.headers["Content-Disposition"]

        # Verify ZIP structure
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as main_zip:
            names = main_zip.namelist()
            # Should have CSV only
            csv_files = [n for n in names if n.endswith(".csv")]
            assert len(csv_files) == 1
            assert "EXTF_Buchungsstapel" in csv_files[0]

    def should_include_nested_zips_when_receipts_have_files(self, api_client, database_session, monkeypatch):
        """POST /datev/download/zip includes nested ZIPs for receipts with files."""
        import io
        import zipfile
        from uuid import uuid4

        import app.services.receipt_storage as storage_module
        from app.models.receipt import Receipt, ReceiptType
        from app.models.receipt_line_item import ReceiptLineItem
        from app.models.receipt_transaction_link import ReceiptTransactionLink

        # Mock get_file_content to return dummy PDF content
        mock_content = b"%PDF-1.4 test content"
        monkeypatch.setattr(storage_module, "get_file_content", lambda *args: mock_content)

        # Create transaction with receipt WITH file
        transaction = _create_example_transaction(
            database_session,
            amount=Decimal("100.00"),
        )
        receipt = Receipt(
            id="receipt-with-file-zip",
            user_id="test-user-id",
            type=ReceiptType.REVENUE,
            receipt_number="INV-ZIP",
            date=date(2026, 1, 15),
            counterparty="Customer",
            file_storage_id="receipts/2026/test.pdf",
            file_hash="abc123def456789",
            file_mime_type="application/pdf",
        )
        database_session.add(receipt)
        database_session.flush()
        line_item = ReceiptLineItem(
            id=str(uuid4()),
            receipt_id=receipt.id,
            position=1,
            description="Service",
            amount=Decimal("100.00"),
            skr03_account_id=8400,
        )
        database_session.add(line_item)
        link = ReceiptTransactionLink(
            receipt_id=receipt.id,
            transaction_id=transaction.id,
        )
        database_session.add(link)
        database_session.commit()

        response = api_client.post("/api/v1/export/datev/download/zip", json=ZIP_EXPORT_REQUEST, headers=AUTH_HEADERS)

        assert response.status_code == 200

        # Verify ZIP structure
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as main_zip:
            names = main_zip.namelist()
            # Should have CSV + nested Rechnungsausgang ZIP (REVENUE)
            csv_files = [n for n in names if n.endswith(".csv")]
            nested_zips = [n for n in names if n.endswith(".zip")]
            assert len(csv_files) == 1
            assert len(nested_zips) == 1
            assert "Rechnungsausgang" in nested_zips[0]

            # Verify nested ZIP contains document.xml
            nested_zip_content = main_zip.read(nested_zips[0])
            nested_buffer = io.BytesIO(nested_zip_content)
            with zipfile.ZipFile(nested_buffer, "r") as nested_zip:
                nested_names = nested_zip.namelist()
                assert "document.xml" in nested_names

    def should_validate_zip_export_with_warnings(self, api_client, database_session):
        """POST /datev/validate/zip returns warnings for receipts without files."""
        from uuid import uuid4

        from app.models.receipt import Receipt, ReceiptType

        # Create receipt WITHOUT file
        receipt = Receipt(
            id=str(uuid4()),
            user_id="test-user-id",
            type=ReceiptType.EXPENSE,
            receipt_number="EXP-NO-FILE",
            date=date(2026, 1, 15),
            counterparty="Supplier",
            # file_storage_id is None
        )
        database_session.add(receipt)
        database_session.commit()

        response = api_client.post("/api/v1/export/datev/validate/zip", json=ZIP_EXPORT_REQUEST, headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True  # Warnings don't block
        assert len(data["warnings"]) >= 1
        assert "Belegbild fehlt" in data["warnings"][0]

    def should_filter_by_document_types(self, api_client, database_session, monkeypatch):
        """POST /datev/download/zip respects document_types filter."""
        import io
        import zipfile
        from uuid import uuid4

        import app.services.receipt_storage as storage_module
        from app.models.receipt import Receipt, ReceiptType
        from app.models.receipt_line_item import ReceiptLineItem
        from app.models.receipt_transaction_link import ReceiptTransactionLink

        # Mock get_file_content
        mock_content = b"%PDF-1.4 test content"
        monkeypatch.setattr(storage_module, "get_file_content", lambda *args: mock_content)

        # Create REVENUE transaction
        tx_revenue = _create_example_transaction(database_session, amount=Decimal("100.00"))
        receipt_revenue = Receipt(
            id="receipt-revenue-filter",
            user_id="test-user-id",
            type=ReceiptType.REVENUE,
            receipt_number="INV-FILTER",
            date=date(2026, 1, 15),
            counterparty="Customer",
            file_storage_id="receipts/2026/revenue.pdf",
            file_hash="revhash123",
            file_mime_type="application/pdf",
        )
        database_session.add(receipt_revenue)
        database_session.flush()
        database_session.add(
            ReceiptLineItem(
                id=str(uuid4()),
                receipt_id=receipt_revenue.id,
                position=1,
                description="Service",
                amount=Decimal("100.00"),
                skr03_account_id=8400,
            )
        )
        database_session.add(ReceiptTransactionLink(receipt_id=receipt_revenue.id, transaction_id=tx_revenue.id))

        # Create EXPENSE transaction
        tx_expense = _create_example_transaction(database_session, amount=Decimal("-50.00"))
        receipt_expense = Receipt(
            id="receipt-expense-filter",
            user_id="test-user-id",
            type=ReceiptType.EXPENSE,
            receipt_number="EXP-FILTER",
            date=date(2026, 1, 20),
            counterparty="Supplier",
            file_storage_id="receipts/2026/expense.pdf",
            file_hash="exphash123",
            file_mime_type="application/pdf",
        )
        database_session.add(receipt_expense)
        database_session.flush()
        database_session.add(
            ReceiptLineItem(
                id=str(uuid4()),
                receipt_id=receipt_expense.id,
                position=1,
                description="Supplies",
                amount=Decimal("-50.00"),
                skr03_account_id=4900,
            )
        )
        database_session.add(ReceiptTransactionLink(receipt_id=receipt_expense.id, transaction_id=tx_expense.id))
        database_session.commit()

        # Request only revenue
        request = {
            **ZIP_EXPORT_REQUEST,
            "document_types": ["revenue"],
        }
        response = api_client.post("/api/v1/export/datev/download/zip", json=request, headers=AUTH_HEADERS)

        assert response.status_code == 200
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as main_zip:
            names = main_zip.namelist()
            nested_zips = [n for n in names if n.endswith(".zip")]
            # Should only have Rechnungsausgang (revenue), no Rechnungseingang (expense)
            assert len(nested_zips) == 1
            assert "Rechnungsausgang" in nested_zips[0]

    def should_return_zip_with_correct_filename(self, api_client, database_session):
        """POST /datev/download/zip returns ZIP with correct filename in Content-Disposition."""
        from uuid import uuid4

        from app.models.receipt import Receipt, ReceiptType
        from app.models.receipt_line_item import ReceiptLineItem
        from app.models.receipt_transaction_link import ReceiptTransactionLink

        # Create transaction with receipt
        transaction = _create_example_transaction(database_session, amount=Decimal("100.00"))
        receipt = Receipt(
            id=str(uuid4()),
            user_id="test-user-id",
            type=ReceiptType.REVENUE,
            receipt_number="INV-LOG",
            date=date(2026, 1, 15),
            counterparty="Customer",
        )
        database_session.add(receipt)
        database_session.flush()
        database_session.add(
            ReceiptLineItem(
                id=str(uuid4()),
                receipt_id=receipt.id,
                position=1,
                description="Service",
                amount=Decimal("100.00"),
                skr03_account_id=8400,
            )
        )
        database_session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id))
        database_session.commit()

        # Download ZIP
        response = api_client.post("/api/v1/export/datev/download/zip", json=ZIP_EXPORT_REQUEST, headers=AUTH_HEADERS)
        assert response.status_code == 200

        # Check Content-Disposition header
        content_disp = response.headers.get("Content-Disposition", "")
        assert "DATEV_Export" in content_disp
        assert ".zip" in content_disp
        assert "20260101" in content_disp  # date_from
        assert "20261231" in content_disp  # date_to

    def should_return_export_format_in_history(self, api_client, database_session):
        """GET /history returns export_format field."""
        from datetime import UTC, datetime

        from app.models.export_log import ExportLog

        # Create export logs with different formats
        csv_log = ExportLog(
            user_id="test-user-id",
            export_type="datev",
            export_format="csv",
            transaction_count=5,
            line_item_count=5,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 6, 30),
            beraternummer="1234567",
            mandantennummer="12345",
            filename="export.csv",
            created_at=datetime.now(UTC),
        )
        zip_log = ExportLog(
            user_id="test-user-id",
            export_type="datev",
            export_format="zip",
            transaction_count=5,
            line_item_count=5,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 6, 30),
            beraternummer="1234567",
            mandantennummer="12345",
            filename="export.zip",
            created_at=datetime.now(UTC),
        )
        database_session.add(csv_log)
        database_session.add(zip_log)
        database_session.commit()

        response = api_client.get("/api/v1/export/history", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        formats = [item["export_format"] for item in data["items"]]
        assert "csv" in formats
        assert "zip" in formats
