"""Tests for DATEV export functionality."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.receipt import Receipt, ReceiptType
from app.models.receipt_line_item import ReceiptLineItem
from app.models.receipt_transaction_link import ReceiptTransactionLink
from app.models.skr03 import AccountCategory, SKR03Account
from app.models.source import SourceType, TransactionSourceConfig
from app.models.transaction import Transaction
from app.schemas.datev import DatevConfig
from app.services.datev import DatevExportService

from tests.conftest import TEST_SOURCE_CONFIG_ID, _ensure_test_source_config

DKB_SOURCE_CONFIG_ID = "b0000000-0000-0000-0000-000000000001"
PAYPAL_SOURCE_CONFIG_ID = "b0000000-0000-0000-0000-000000000002"
ETSY_SOURCE_CONFIG_ID = "b0000000-0000-0000-0000-000000000003"


def _ensure_dkb_source_config(session) -> str:
    """Ensure a DKB (bank) source config exists for gegenkonto=1200 tests."""
    existing = session.get(TransactionSourceConfig, DKB_SOURCE_CONFIG_ID)
    if not existing:
        session.add(
            TransactionSourceConfig(
                id=DKB_SOURCE_CONFIG_ID,
                user_id=None,
                name="DKB",
                type=SourceType.CSV_MAPPING,
                check_account_id=1200,
            )
        )
        session.flush()
    return DKB_SOURCE_CONFIG_ID


def _ensure_paypal_source_config(session) -> str:
    """Ensure a PayPal source config exists for gegenkonto=1210 tests."""
    existing = session.get(TransactionSourceConfig, PAYPAL_SOURCE_CONFIG_ID)
    if not existing:
        session.add(
            TransactionSourceConfig(
                id=PAYPAL_SOURCE_CONFIG_ID,
                user_id=None,
                name="PayPal",
                type=SourceType.API_SYNC,
                check_account_id=1210,
            )
        )
        session.flush()
    return PAYPAL_SOURCE_CONFIG_ID


def _ensure_etsy_source_config(session) -> str:
    """Ensure an Etsy source config exists for gegenkonto=1201 tests (D4/D9: virtual bank)."""
    existing = session.get(TransactionSourceConfig, ETSY_SOURCE_CONFIG_ID)
    if not existing:
        session.add(
            TransactionSourceConfig(
                id=ETSY_SOURCE_CONFIG_ID,
                user_id=None,
                name="Etsy",
                type=SourceType.MARKETPLACE_MAPPING,
                check_account_id=1201,  # Etsy Payments virtual bank per D4/D9
                source_config={"has_ust_id_registered": True, "vat_id": "IE9777587C"},
            )
        )
        session.flush()
    return ETSY_SOURCE_CONFIG_ID


@pytest.fixture
def datev_config() -> DatevConfig:
    """Standard DATEV configuration for tests."""
    return DatevConfig(
        beraternummer="1234567",
        mandantennummer="12345",
        wirtschaftsjahr_beginn=date(2026, 1, 1),
        sachkontenlaenge=4,
    )


@pytest.fixture
def seeded_with_source_configs(seeded_session, example_user):
    """Seeded session with source configs and example user."""
    # Ensure source configs with correct check_account_ids exist
    _ensure_dkb_source_config(seeded_session)
    _ensure_paypal_source_config(seeded_session)
    _ensure_etsy_source_config(seeded_session)
    seeded_session.commit()
    return seeded_session


def _link_receipt_with_line_items(
    session,
    transaction: Transaction,
    line_items: list[tuple[int, Decimal, str]],
) -> Receipt:
    """Create a receipt with line items and link it to a transaction.

    Args:
        session: Database session
        transaction: Transaction to link
        line_items: List of (skr03_account_id, amount, description) tuples
    """
    receipt = Receipt(
        id=str(uuid4()),
        user_id=transaction.user_id,
        type=ReceiptType.REVENUE,
        receipt_number=f"INV-{transaction.id[:8]}",
        date=transaction.date,
        counterparty=transaction.counterparty,
    )
    session.add(receipt)
    session.flush()

    for position, (skr03_account_id, amount, description) in enumerate(line_items):
        session.add(
            ReceiptLineItem(
                id=str(uuid4()),
                receipt_id=receipt.id,
                position=position,
                skr03_account_id=skr03_account_id,
                amount=amount,
                description=description,
            )
        )

    session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id))
    session.flush()
    return receipt


class TestDatevHeaderBlock:
    """Tests for DATEV header block generation."""

    def should_generate_valid_extf_header(self, database_session, datev_config):
        """Header should start with EXTF identifier."""
        service = DatevExportService(database_session)
        header = service.generate_header_block(datev_config, None, None)

        assert len(header) >= 1
        assert header[0].startswith('"EXTF"')

    def should_include_beraternummer_in_header(self, database_session, datev_config):
        """Header should contain consultant number."""
        service = DatevExportService(database_session)
        header = service.generate_header_block(datev_config, None, None)

        assert "1234567" in header[0]

    def should_include_mandantennummer_in_header(self, database_session, datev_config):
        """Header should contain client number."""
        service = DatevExportService(database_session)
        header = service.generate_header_block(datev_config, None, None)

        assert "12345" in header[0]

    def should_include_wirtschaftsjahr_in_header(self, database_session, datev_config):
        """Header should contain fiscal year start."""
        service = DatevExportService(database_session)
        header = service.generate_header_block(datev_config, None, None)

        assert "20260101" in header[0]


class TestGegenkontoDerivation:
    """Tests for contra account (Gegenkonto) derivation from source_config."""

    def should_read_check_account_from_source_config(self, seeded_with_source_configs, example_user):
        """Gegenkonto should come from source_config.check_account_id."""
        session = seeded_with_source_configs

        # Create transaction with DKB source (check_account_id=1200)
        transaction = Transaction(
            id="tx-dkb",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Test",
            description="Test",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        gegenkonto = service.get_gegenkonto(transaction)

        assert gegenkonto == 1200

    def should_use_paypal_check_account(self, seeded_with_source_configs, example_user):
        """PayPal transactions should use 1210 from source_config."""
        session = seeded_with_source_configs

        transaction = Transaction(
            id="tx-paypal",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Test",
            description="Test",
            source_config_id=PAYPAL_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        gegenkonto = service.get_gegenkonto(transaction)

        assert gegenkonto == 1210

    def should_use_marketplace_check_account(self, seeded_with_source_configs, example_user):
        """Marketplace sources should use virtual bank (1201 for Etsy per D4/D9)."""
        session = seeded_with_source_configs

        transaction = Transaction(
            id="tx-etsy",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Test",
            description="Test",
            source_config_id=ETSY_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        gegenkonto = service.get_gegenkonto(transaction)

        assert gegenkonto == 1201  # Etsy Payments virtual bank per D4/D9

    def should_default_to_bank_when_no_source_config(self, seeded_with_source_configs, example_user):
        """Transactions without source_config should default to 1200 (Bank)."""
        session = seeded_with_source_configs
        _ensure_test_source_config(session)

        # Create transaction without source_config relationship loaded
        # (simulating edge case where source_config is None)
        transaction = Transaction(
            id="tx-no-source",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Test",
            description="Test",
            source_config_id=TEST_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        # Manually set source_config to None to test fallback
        transaction.source_config = None

        service = DatevExportService(session)
        gegenkonto = service.get_gegenkonto(transaction)

        assert gegenkonto == 1200


class TestBuSchluesselMapping:
    """Tests for BU-Schlüssel (tax key) mapping."""

    def should_get_bu_schluessel_from_account(self, database_session):
        """BU-Schlüssel should come from SKR03 account."""
        account = SKR03Account(
            id=8400,
            name="Erlöse 19% USt",
            category=AccountCategory.REVENUE,
            bu_schluessel=3,
        )

        service = DatevExportService(database_session)
        bu_schluessel = service.get_bu_schluessel(account)

        assert bu_schluessel == 3

    def should_return_none_for_account_without_bu(self, database_session):
        """Accounts without BU-Schlüssel should return None."""
        account = SKR03Account(
            id=1800,
            name="Privatentnahme",
            category=AccountCategory.NEUTRAL,
            bu_schluessel=None,
        )

        service = DatevExportService(database_session)
        bu_schluessel = service.get_bu_schluessel(account)

        assert bu_schluessel is None


class TestVatCalculation:
    """Tests for VAT amount calculation."""

    def should_calculate_19_percent_vat(self, database_session):
        """Should correctly calculate 19% VAT from gross amount."""
        service = DatevExportService(database_session)
        net, vat = service.calculate_vat_amounts(Decimal("119.00"), 3)

        assert net == Decimal("100.00")
        assert vat == Decimal("19.00")

    def should_calculate_7_percent_vat(self, database_session):
        """Should correctly calculate 7% VAT from gross amount."""
        service = DatevExportService(database_session)
        net, vat = service.calculate_vat_amounts(Decimal("107.00"), 2)

        assert net == Decimal("100.00")
        assert vat == Decimal("7.00")

    def should_return_none_for_no_bu_schluessel(self, database_session):
        """Without BU-Schlüssel, should return None for both amounts."""
        service = DatevExportService(database_session)
        net, vat = service.calculate_vat_amounts(Decimal("100.00"), None)

        assert net is None
        assert vat is None


class TestTransactionToBookingLine:
    """Tests for converting transactions to DATEV booking lines."""

    def should_convert_transaction_with_receipt(self, seeded_with_source_configs, example_user):
        """Transaction with linked receipt should produce booking lines from receipt line items."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        transaction = Transaction(
            id="tx-001",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("119.00"),
            counterparty="Customer GmbH",
            description="Invoice 001",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        _link_receipt_with_line_items(
            session,
            transaction,
            [
                (8400, Decimal("119.00"), "Product sale"),
            ],
        )
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        booking_lines = service.transaction_to_booking_lines(transaction)

        assert len(booking_lines) == 1
        bz = booking_lines[0]
        assert bz.umsatz == Decimal("119.00")
        assert bz.soll_haben == "H"  # Positive amount = Haben
        assert bz.konto == 8400
        assert bz.gegenkonto == 1200  # DKB → Bank
        assert bz.bu_schluessel == 3

    def should_convert_multi_line_receipt(self, seeded_with_source_configs, example_user):
        """Receipt with multiple line items should produce multiple booking lines."""
        session = seeded_with_source_configs
        _ensure_test_source_config(session)

        transaction = Transaction(
            id="tx-002",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("200.00"),
            counterparty="Customer GmbH",
            description="Mixed invoice",
            source_config_id=TEST_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        _link_receipt_with_line_items(
            session,
            transaction,
            [
                (8400, Decimal("119.00"), "19% product"),
                (8300, Decimal("81.00"), "7% product"),
            ],
        )
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        booking_lines = service.transaction_to_booking_lines(transaction)

        assert len(booking_lines) == 2
        assert booking_lines[0].konto == 8400
        assert booking_lines[0].umsatz == Decimal("119.00")
        assert booking_lines[1].konto == 8300
        assert booking_lines[1].umsatz == Decimal("81.00")

    def should_return_empty_for_unlinked_transaction(self, seeded_with_source_configs, example_user):
        """Transaction without receipts should produce zero booking lines."""
        session = seeded_with_source_configs
        _ensure_test_source_config(session)

        transaction = Transaction(
            id="tx-003",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("-50.00"),
            counterparty="DHL",
            description="Shipping",
            source_config_id=TEST_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        service = DatevExportService(session)
        booking_lines = service.transaction_to_booking_lines(transaction)

        assert len(booking_lines) == 0


class TestDatevExport:
    """Tests for complete DATEV export."""

    def should_exclude_private_transactions(self, seeded_with_source_configs, example_user, datev_config):
        """Private transactions should be excluded from export."""
        session = seeded_with_source_configs

        _ensure_test_source_config(session)

        # Create public transaction with linked receipt
        public_tx = Transaction(
            id="tx-public",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Customer",
            description="Business",
            is_private=False,
            source_config_id=TEST_SOURCE_CONFIG_ID,
        )
        session.add(public_tx)
        session.flush()
        _link_receipt_with_line_items(
            session,
            public_tx,
            [
                (8400, Decimal("100.00"), "Revenue"),
            ],
        )

        # Create private transaction with linked receipt
        private_tx = Transaction(
            id="tx-private",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("50.00"),
            counterparty="Private",
            description="Personal",
            is_private=True,
            source_config_id=TEST_SOURCE_CONFIG_ID,
        )
        session.add(private_tx)
        session.flush()
        _link_receipt_with_line_items(
            session,
            private_tx,
            [
                (8400, Decimal("50.00"), "Private purchase"),
            ],
        )
        session.commit()

        service = DatevExportService(session)
        export = service.export(
            config=datev_config,
            include_unreconciled=False,
        )

        assert export.transaction_count == 1
        assert len(export.rows) == 1

    def should_only_export_transactions_with_receipts(self, seeded_with_source_configs, example_user, datev_config):
        """Only transactions with linked receipts are exported."""
        session = seeded_with_source_configs

        _ensure_test_source_config(session)

        # Transaction with linked receipt (should be exported)
        linked_tx = Transaction(
            id="tx-linked",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Customer",
            description="With receipt",
            source_config_id=TEST_SOURCE_CONFIG_ID,
        )
        session.add(linked_tx)
        session.flush()
        _link_receipt_with_line_items(
            session,
            linked_tx,
            [
                (8400, Decimal("100.00"), "Revenue"),
            ],
        )

        # Transaction without receipt (should NOT be exported)
        unlinked_tx = Transaction(
            id="tx-unlinked",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("50.00"),
            counterparty="Customer 2",
            description="No receipt",
            source_config_id=TEST_SOURCE_CONFIG_ID,
        )
        session.add(unlinked_tx)
        session.commit()

        service = DatevExportService(session)

        # Default: only transactions with linked receipts
        export = service.export(config=datev_config, include_unreconciled=False)
        assert export.transaction_count == 1

        # include_unreconciled returns ALL transactions but only receipts produce booking lines
        export_all = service.export(config=datev_config, include_unreconciled=True)
        assert export_all.transaction_count == 2
        assert export_all.line_item_count == 1  # Only linked transaction has booking lines

    def should_generate_valid_csv_content(self, seeded_with_source_configs, example_user, datev_config):
        """Export should generate semicolon-delimited CSV content."""
        session = seeded_with_source_configs

        _ensure_test_source_config(session)

        transaction = Transaction(
            id="tx-csv-test",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("119.00"),
            counterparty="Test GmbH",
            description="Invoice",
            source_config_id=TEST_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()
        _link_receipt_with_line_items(
            session,
            transaction,
            [
                (8400, Decimal("119.00"), "Product"),
            ],
        )
        session.commit()

        service = DatevExportService(session)
        export = service.export(config=datev_config)

        # Check CSV content
        assert '"EXTF"' in export.csv_content
        assert ";" in export.csv_content  # Semicolon delimiter
        assert "119,00" in export.csv_content  # German decimal format
        assert "8400" in export.csv_content  # Account number


class TestDatevValidation:
    """Tests for DATEV format validation."""

    def should_validate_valid_export(self, seeded_with_source_configs, example_user, datev_config):
        """Valid export should pass validation."""
        session = seeded_with_source_configs

        _ensure_test_source_config(session)

        transaction = Transaction(
            id="tx-valid",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Customer",
            description="Valid",
            source_config_id=TEST_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()
        _link_receipt_with_line_items(
            session,
            transaction,
            [
                (8400, Decimal("100.00"), "Revenue"),
            ],
        )
        session.commit()

        service = DatevExportService(session)
        export = service.export(config=datev_config)
        validation = service.validate(export)

        assert validation.valid
        assert len(validation.errors) == 0

    def should_warn_on_empty_export(self, seeded_with_source_configs, example_user, datev_config):
        """Empty export should produce warning."""
        service = DatevExportService(seeded_with_source_configs)
        export = service.export(config=datev_config)
        validation = service.validate(export)

        assert validation.valid  # Empty is valid, just warned
        assert "no transactions" in " ".join(validation.warnings).lower()


class TestStornoHandling:
    """Tests for Storno (cancellation/refund) handling in DATEV export."""

    def should_export_storno_as_soll_booking(self, seeded_with_source_configs, example_user, datev_config):
        """Negative Revenue-Receipt (Storno/Gutschrift) should produce Soll booking instead of Haben."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        # Create transaction with negative amount (refund/cancellation)
        transaction = Transaction(
            id="tx-storno",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("-119.00"),  # Negative = Storno
            counterparty="Customer GmbH",
            description="Storno Invoice 001",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        # Create receipt with negative line items (Storno)
        _link_receipt_with_line_items(
            session,
            transaction,
            [
                (8400, Decimal("-119.00"), "Storno: Product sale"),  # Negative amount
            ],
        )
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        booking_lines = service.transaction_to_booking_lines(transaction)

        assert len(booking_lines) == 1
        bz = booking_lines[0]
        # Negative Revenue → Soll (not Haben)
        assert bz.soll_haben == "S"  # Storno reverses the normal Haben booking
        assert bz.umsatz == Decimal("119.00")  # Absolute value
        assert bz.konto == 8400

    def should_export_negative_line_item_correctly(self, seeded_with_source_configs, example_user, datev_config):
        """Rabatt (discount) as negative line item should be handled correctly in export."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        # Create transaction with mixed line items (positive product, negative discount)
        transaction = Transaction(
            id="tx-discount",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("109.00"),  # 119 - 10 = 109
            counterparty="Customer GmbH",
            description="Invoice with discount",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        # Create receipt with positive and negative line items
        _link_receipt_with_line_items(
            session,
            transaction,
            [
                (8400, Decimal("119.00"), "Product sale"),
                (8400, Decimal("-10.00"), "Rabatt"),  # Negative discount
            ],
        )
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        booking_lines = service.transaction_to_booking_lines(transaction)

        assert len(booking_lines) == 2

        # First line: positive = Haben
        assert booking_lines[0].umsatz == Decimal("119.00")
        assert booking_lines[0].soll_haben == "H"

        # Second line: negative (discount) = Soll (reversal)
        assert booking_lines[1].umsatz == Decimal("10.00")  # Absolute value
        assert booking_lines[1].soll_haben == "S"  # Reversed due to negative

    def should_handle_expense_storno(self, seeded_with_source_configs, example_user, datev_config):
        """Negative Expense-Receipt (refund from supplier) should produce Haben booking."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        # Create negative expense transaction (refund from supplier)
        transaction = Transaction(
            id="tx-expense-refund",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("50.00"),  # Positive because we received money back
            counterparty="Supplier GmbH",
            description="Refund for returned goods",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        # Create expense receipt with negative amount (refund)
        receipt = Receipt(
            id=str(uuid4()),
            user_id=example_user.id,
            type=ReceiptType.EXPENSE,
            receipt_number=f"REF-{transaction.id[:8]}",
            date=transaction.date,
            counterparty=transaction.counterparty,
        )
        session.add(receipt)
        session.flush()

        session.add(
            ReceiptLineItem(
                id=str(uuid4()),
                receipt_id=receipt.id,
                position=0,
                skr03_account_id=4900,  # Sonstige betriebliche Aufwendungen
                amount=Decimal("-50.00"),  # Negative expense = refund
                description="Refund",
            )
        )
        session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id))
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        booking_lines = service.transaction_to_booking_lines(transaction)

        assert len(booking_lines) == 1
        bz = booking_lines[0]
        # Negative Expense → Haben (not Soll)
        # Normal expense is Soll, negative expense reverses to Haben
        assert bz.soll_haben == "H"
        assert bz.umsatz == Decimal("50.00")


class TestDatev124Columns:
    """Tests for 124-column DATEV format (sevdesk compatibility)."""

    def should_generate_row_with_124_columns(self, seeded_with_source_configs, example_user):
        """Each booking line row should have exactly 124 columns."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        transaction = Transaction(
            id="tx-124col",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("119.00"),
            counterparty="Customer GmbH",
            description="Invoice 001",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        _link_receipt_with_line_items(
            session,
            transaction,
            [(8400, Decimal("119.00"), "Product sale")],
        )
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        booking_lines = service.transaction_to_booking_lines(transaction)
        row = service.booking_line_to_row(booking_lines[0])

        assert len(row) == 124

    def should_have_124_column_headers(self, database_session):
        """DATEV_COLUMNS should have exactly 124 entries."""
        assert len(DatevExportService.DATEV_COLUMNS) == 124

    def should_include_beleginfo_labels_at_correct_positions(self, database_session):
        """Beleginfo-Art fields should be at positions 21, 23, 25, etc."""
        columns = DatevExportService.DATEV_COLUMNS
        # 0-indexed: positions 20, 22, 24, 26, 28, 30, 32, 34
        assert columns[20] == "Beleginfo-Art 1"
        assert columns[22] == "Beleginfo-Art 2"
        assert columns[24] == "Beleginfo-Art 3"
        assert columns[28] == "Beleginfo-Art 5"
        assert columns[30] == "Beleginfo-Art 6"
        assert columns[32] == "Beleginfo-Art 7"


class TestDatevEncoding:
    """Tests for CSV encoding (ISO-8859-1 / Latin-1)."""

    def should_generate_bytes_in_latin1_encoding(self, seeded_with_source_configs, example_user, datev_config):
        """CSV output should be Latin-1 encoded, not UTF-8."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        transaction = Transaction(
            id="tx-enc",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Müller GmbH",  # Umlaut test
            description="Test",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        _link_receipt_with_line_items(session, transaction, [(8400, Decimal("100.00"), "Test")])
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        export = service.export(config=datev_config)

        # Get raw bytes
        csv_bytes = service.generate_csv_bytes(export.header, export.column_headers, export.rows)

        # Should be decodable as Latin-1
        decoded = csv_bytes.decode("latin-1")
        assert "Müller" in decoded

        # Column header with umlaut should be present
        assert "BU-Schlüssel" in decoded

    def should_use_lf_line_endings(self, seeded_with_source_configs, example_user, datev_config):
        """CSV should use LF line endings, not CRLF."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        transaction = Transaction(
            id="tx-lf",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Test",
            description="Test",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        _link_receipt_with_line_items(session, transaction, [(8400, Decimal("100.00"), "Test")])
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        export = service.export(config=datev_config)
        csv_bytes = service.generate_csv_bytes(export.header, export.column_headers, export.rows)

        # Should not contain CRLF
        assert b"\r\n" not in csv_bytes
        # Should contain LF
        assert b"\n" in csv_bytes


class TestExtfHeader:
    """Tests for EXTF header format (31 fields)."""

    def should_have_31_semicolon_separated_fields(self, database_session, datev_config):
        """EXTF header should have exactly 31 fields."""
        service = DatevExportService(database_session)
        header = service.generate_header_block(datev_config, None, None)

        # Header should have 1 line
        assert len(header) == 1

        # Count semicolons (31 fields = 30 separators, but we have 31 including trailing)
        fields = header[0].split(";")
        assert len(fields) == 31

    def should_start_with_extf_identifier(self, database_session, datev_config):
        """Header should start with EXTF."""
        service = DatevExportService(database_session)
        header = service.generate_header_block(datev_config, None, None)

        assert header[0].startswith('"EXTF"')

    def should_have_empty_fields_at_positions_6_7(self, database_session, datev_config):
        """Positions 6 and 7 should be empty (not timestamp like old format)."""
        service = DatevExportService(database_session)
        header = service.generate_header_block(datev_config, None, None)

        fields = header[0].split(";")
        # 0-indexed: positions 5 and 6
        assert fields[5] == ""
        assert fields[6] == ""

    def should_have_festschreibung_at_position_21(self, database_session, datev_config):
        """Position 21 should be Festschreibung (0 = not locked)."""
        service = DatevExportService(database_session)
        header = service.generate_header_block(datev_config, None, None)

        fields = header[0].split(";")
        # 0-indexed: position 20
        assert fields[20] == "0"


class TestBeleglink:
    """Tests for Beleglink (BEDI GUID) functionality."""

    def should_generate_beleglink_for_receipt_with_file(self, seeded_with_source_configs, example_user):
        """Receipt with file should have a BEDI GUID in beleglink."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        transaction = Transaction(
            id="tx-bedi",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Test",
            description="Test",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        # Create receipt WITH file
        receipt = Receipt(
            id="receipt-with-file",
            user_id=example_user.id,
            type=ReceiptType.REVENUE,
            receipt_number="INV-001",
            date=transaction.date,
            counterparty=transaction.counterparty,
            file_storage_id="receipts/2026/abc123.pdf",
            file_hash="abc123def456",
        )
        session.add(receipt)
        session.flush()

        session.add(
            ReceiptLineItem(
                id=str(uuid4()),
                receipt_id=receipt.id,
                position=0,
                skr03_account_id=8400,
                amount=Decimal("100.00"),
                description="Test",
            )
        )
        session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id))
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        booking_lines = service.transaction_to_booking_lines(transaction)

        assert len(booking_lines) == 1
        bz = booking_lines[0]

        # Should have beleglink
        assert bz.beleglink is not None
        assert bz.beleglink.startswith('BEDI "')
        assert bz.beleglink.endswith('"')

    def should_have_empty_beleglink_for_receipt_without_file(self, seeded_with_source_configs, example_user):
        """Receipt without file should have empty beleglink."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        transaction = Transaction(
            id="tx-nobedi",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Test",
            description="Test",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        _link_receipt_with_line_items(session, transaction, [(8400, Decimal("100.00"), "Test")])
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        booking_lines = service.transaction_to_booking_lines(transaction)

        assert len(booking_lines) == 1
        bz = booking_lines[0]

        # Should NOT have beleglink
        assert bz.beleglink is None

    def should_have_beleglink_at_row_position_20(self, seeded_with_source_configs, example_user):
        """Beleglink should be at row index 19 (position 20)."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        transaction = Transaction(
            id="tx-pos20",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Test",
            description="Test",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        # Create receipt WITH file
        receipt = Receipt(
            id="receipt-pos20",
            user_id=example_user.id,
            type=ReceiptType.REVENUE,
            receipt_number="INV-002",
            date=transaction.date,
            counterparty=transaction.counterparty,
            file_storage_id="receipts/2026/xyz789.pdf",
            file_hash="xyz789abc",
        )
        session.add(receipt)
        session.flush()

        session.add(
            ReceiptLineItem(
                id=str(uuid4()),
                receipt_id=receipt.id,
                position=0,
                skr03_account_id=8400,
                amount=Decimal("100.00"),
                description="Test",
            )
        )
        session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id))
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)
        booking_lines = service.transaction_to_booking_lines(transaction)
        row = service.booking_line_to_row(booking_lines[0])

        # Position 20 (0-indexed: 19)
        assert row[19].startswith('BEDI "')


class TestUuidV5Determinism:
    """Tests for UUID v5 deterministic generation."""

    def should_generate_same_uuid_for_same_receipt_id(self):
        """Same receipt ID should produce same BEDI GUID across calls."""
        from app.services.datev import generate_bedi_guid

        receipt_id = "test-receipt-123"

        uuid1 = generate_bedi_guid(receipt_id)
        uuid2 = generate_bedi_guid(receipt_id)
        uuid3 = generate_bedi_guid(receipt_id)

        assert uuid1 == uuid2 == uuid3

    def should_generate_different_uuid_for_different_receipt_id(self):
        """Different receipt IDs should produce different GUIDs."""
        from app.services.datev import generate_bedi_guid

        uuid1 = generate_bedi_guid("receipt-a")
        uuid2 = generate_bedi_guid("receipt-b")

        assert uuid1 != uuid2

    def should_generate_valid_uuid_format(self):
        """Generated GUID should be valid UUID format."""
        import uuid as uuid_module

        from app.services.datev import generate_bedi_guid

        result = generate_bedi_guid("test-receipt")

        # Should be parseable as UUID
        parsed = uuid_module.UUID(result)
        assert str(parsed) == result

        # UUID v5 has version byte = 5
        assert parsed.version == 5


class TestDocumentXml:
    """Tests for document.xml generation."""

    def should_generate_valid_xml_structure(self, seeded_with_source_configs, example_user):
        """document.xml should have correct namespace and structure."""
        import xml.etree.ElementTree as ET

        session = seeded_with_source_configs

        receipt = Receipt(
            id="receipt-xml-test",
            user_id=example_user.id,
            type=ReceiptType.REVENUE,
            receipt_number="INV-XML",
            date=date(2026, 2, 15),
            counterparty="Test",
            file_storage_id="receipts/2026/test.pdf",
            file_hash="testhash123456",
        )
        session.add(receipt)
        session.commit()

        service = DatevExportService(session)
        xml_bytes = service.generate_document_xml([receipt], ReceiptType.REVENUE)

        # Should start with XML declaration
        assert xml_bytes.startswith(b'<?xml version="1.0"')

        # Parse XML
        root = ET.fromstring(xml_bytes)

        # Check root element
        assert "archive" in root.tag

        # Check generatingSystem attribute
        assert root.get("generatingSystem") == "shop2tax"

        # Check version
        assert root.get("version") == "6.0"

    def should_skip_receipts_without_files(self, seeded_with_source_configs, example_user):
        """Receipts without files should not appear in document.xml."""
        import xml.etree.ElementTree as ET

        session = seeded_with_source_configs

        # Receipt WITH file
        receipt_with_file = Receipt(
            id="receipt-with-file-xml",
            user_id=example_user.id,
            type=ReceiptType.EXPENSE,
            receipt_number="EXP-FILE",
            date=date(2026, 2, 15),
            counterparty="Supplier",
            file_storage_id="receipts/2026/file.pdf",
            file_hash="filehash",
        )
        # Receipt WITHOUT file
        receipt_no_file = Receipt(
            id="receipt-no-file-xml",
            user_id=example_user.id,
            type=ReceiptType.EXPENSE,
            receipt_number="EXP-NOFILE",
            date=date(2026, 2, 15),
            counterparty="Supplier2",
            # file_storage_id is None
        )
        session.add(receipt_with_file)
        session.add(receipt_no_file)
        session.commit()

        service = DatevExportService(session)
        xml_bytes = service.generate_document_xml([receipt_with_file, receipt_no_file], ReceiptType.EXPENSE)

        root = ET.fromstring(xml_bytes)
        namespaces = {"datev": "http://xml.datev.de/bedi/tps/document/v06.0"}
        documents = root.findall(".//datev:document", namespaces)

        # Only receipt with file should appear
        assert len(documents) == 1

    def should_include_document_elements_with_guid_and_type(self, seeded_with_source_configs, example_user):
        """Each receipt should have a document element with guid and type."""
        import xml.etree.ElementTree as ET

        session = seeded_with_source_configs

        receipt = Receipt(
            id="receipt-doc-elem",
            user_id=example_user.id,
            type=ReceiptType.EXPENSE,
            receipt_number="EXP-001",
            date=date(2026, 2, 15),
            counterparty="Supplier",
            file_storage_id="receipts/2026/expense.pdf",
            file_hash="expensehash",
        )
        session.add(receipt)
        session.commit()

        service = DatevExportService(session)
        xml_bytes = service.generate_document_xml([receipt], ReceiptType.EXPENSE)

        root = ET.fromstring(xml_bytes)

        # Find document element (need to handle namespace)
        namespaces = {"datev": "http://xml.datev.de/bedi/tps/document/v06.0"}
        documents = root.findall(".//datev:document", namespaces)

        assert len(documents) == 1
        doc = documents[0]

        # Check guid matches
        from app.services.datev import generate_bedi_guid

        expected_guid = generate_bedi_guid("receipt-doc-elem")
        assert doc.get("guid") == expected_guid

        # Check type (1 = EXPENSE/Rechnungseingang)
        assert doc.get("type") == "1"

    def should_use_type_2_for_revenue_receipts(self, seeded_with_source_configs, example_user):
        """REVENUE receipts should have type=2 (Rechnungsausgang)."""
        import xml.etree.ElementTree as ET

        session = seeded_with_source_configs

        receipt = Receipt(
            id="receipt-revenue-type",
            user_id=example_user.id,
            type=ReceiptType.REVENUE,
            receipt_number="REV-001",
            date=date(2026, 2, 15),
            counterparty="Customer",
            file_storage_id="receipts/2026/revenue.pdf",
            file_hash="revenuehash",
        )
        session.add(receipt)
        session.commit()

        service = DatevExportService(session)
        xml_bytes = service.generate_document_xml([receipt], ReceiptType.REVENUE)

        root = ET.fromstring(xml_bytes)
        namespaces = {"datev": "http://xml.datev.de/bedi/tps/document/v06.0"}
        documents = root.findall(".//datev:document", namespaces)

        assert len(documents) == 1
        assert documents[0].get("type") == "2"  # REVENUE = Rechnungsausgang = type 2


class TestBediGuidConsistency:
    """Tests for BEDI GUID consistency between CSV and document.xml."""

    def should_have_consistent_guid_in_csv_and_xml(self, seeded_with_source_configs, example_user):
        """Same BEDI GUID should appear in CSV column 20 and document.xml."""
        import xml.etree.ElementTree as ET

        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        receipt_id = "receipt-consistency-test"

        # Create transaction with receipt that has a file
        transaction = Transaction(
            id="tx-consistency",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Test",
            description="Test",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        receipt = Receipt(
            id=receipt_id,
            user_id=example_user.id,
            type=ReceiptType.REVENUE,
            receipt_number="INV-CONSISTENT",
            date=transaction.date,
            counterparty=transaction.counterparty,
            file_storage_id="receipts/2026/consistent.pdf",
            file_hash="consistenthash",
        )
        session.add(receipt)
        session.flush()

        session.add(
            ReceiptLineItem(
                id=str(uuid4()),
                receipt_id=receipt.id,
                position=0,
                skr03_account_id=8400,
                amount=Decimal("100.00"),
                description="Test",
            )
        )
        session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id))
        session.flush()
        session.refresh(transaction)

        service = DatevExportService(session)

        # Get GUID from CSV
        booking_lines = service.transaction_to_booking_lines(transaction)
        assert len(booking_lines) == 1
        beleglink = booking_lines[0].beleglink
        assert beleglink is not None
        # Extract UUID from BEDI "uuid" format
        csv_guid = beleglink.replace('BEDI "', "").replace('"', "")

        # Get GUID from XML
        xml_bytes = service.generate_document_xml([receipt], ReceiptType.REVENUE)
        root = ET.fromstring(xml_bytes)
        namespaces = {"datev": "http://xml.datev.de/bedi/tps/document/v06.0"}
        documents = root.findall(".//datev:document", namespaces)
        assert len(documents) == 1
        xml_guid = documents[0].get("guid")

        # GUIDs must match
        assert csv_guid == xml_guid

    def should_produce_bedi_quoted_format_in_raw_csv_bytes(self, seeded_with_source_configs, example_user, datev_config):
        """Raw CSV bytes should contain BEDI ""uuid"" (escaped double quotes)."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        # Create transaction with receipt that has a file
        transaction = Transaction(
            id="tx-raw-bytes",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Test",
            description="Test",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        receipt = Receipt(
            id="receipt-raw-bytes",
            user_id=example_user.id,
            type=ReceiptType.REVENUE,
            receipt_number="INV-RAW",
            date=transaction.date,
            counterparty=transaction.counterparty,
            file_storage_id="receipts/2026/raw.pdf",
            file_hash="rawhash",
        )
        session.add(receipt)
        session.flush()

        session.add(
            ReceiptLineItem(
                id=str(uuid4()),
                receipt_id=receipt.id,
                position=0,
                skr03_account_id=8400,
                amount=Decimal("100.00"),
                description="Test",
            )
        )
        session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id))
        session.commit()

        service = DatevExportService(session)
        export = service.export(config=datev_config)
        csv_bytes = service.generate_csv_bytes(export.header, export.column_headers, export.rows)

        # Decode and check for escaped quotes
        csv_text = csv_bytes.decode("latin-1")

        # The raw CSV should have BEDI ""uuid"" (escaped double quotes in CSV)
        # When csv.writer encounters BEDI "uuid", it outputs "BEDI ""uuid"""
        assert 'BEDI ""' in csv_text


class TestZipExportService:
    """Tests for ZIP export service functionality."""

    def should_return_receipts_without_file_list(self, seeded_with_source_configs, example_user, datev_config):
        """export_zip should return list of receipts without files."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        # Create transaction with receipt WITHOUT file
        transaction = Transaction(
            id="tx-no-file-list",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Test",
            description="Test",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        receipt = Receipt(
            id=str(uuid4()),
            user_id=example_user.id,
            type=ReceiptType.REVENUE,
            receipt_number="INV-NOFILE",
            date=transaction.date,
            counterparty=transaction.counterparty,
            # file_storage_id is None
        )
        session.add(receipt)
        session.flush()

        session.add(
            ReceiptLineItem(
                id=str(uuid4()),
                receipt_id=receipt.id,
                position=0,
                skr03_account_id=8400,
                amount=Decimal("100.00"),
                description="Test",
            )
        )
        session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id))
        session.commit()

        service = DatevExportService(session)
        result = service.export_zip(config=datev_config)

        # Should list receipt without file
        assert "INV-NOFILE" in result.receipts_without_file

    def should_filter_by_finalized_only(self, seeded_with_source_configs, example_user, datev_config, monkeypatch):
        """export_zip should filter by finalized_only when set."""
        import app.services.receipt_storage as storage_module
        from app.models.receipt import ReceiptStatus

        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        # Mock get_file_content
        mock_content = b"%PDF-1.4 test content"
        monkeypatch.setattr(storage_module, "get_file_content", lambda *args: mock_content)

        # Create FINAL receipt
        tx_final = Transaction(
            id="tx-final",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("100.00"),
            counterparty="Test",
            description="Test",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(tx_final)
        session.flush()

        receipt_final = Receipt(
            id="receipt-final",
            user_id=example_user.id,
            type=ReceiptType.REVENUE,
            receipt_number="INV-FINAL",
            date=tx_final.date,
            counterparty=tx_final.counterparty,
            file_storage_id="receipts/2026/final.pdf",
            file_hash="finalhash",
            status=ReceiptStatus.FINAL,
        )
        session.add(receipt_final)
        session.flush()
        session.add(
            ReceiptLineItem(
                id=str(uuid4()),
                receipt_id=receipt_final.id,
                position=0,
                skr03_account_id=8400,
                amount=Decimal("100.00"),
                description="Test",
            )
        )
        session.add(ReceiptTransactionLink(receipt_id=receipt_final.id, transaction_id=tx_final.id))

        # Create DRAFT receipt
        tx_draft = Transaction(
            id="tx-draft",
            user_id=example_user.id,
            date=date(2026, 2, 16),
            amount=Decimal("50.00"),
            counterparty="Test2",
            description="Test2",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(tx_draft)
        session.flush()

        receipt_draft = Receipt(
            id="receipt-draft",
            user_id=example_user.id,
            type=ReceiptType.REVENUE,
            receipt_number="INV-DRAFT",
            date=tx_draft.date,
            counterparty=tx_draft.counterparty,
            file_storage_id="receipts/2026/draft.pdf",
            file_hash="drafthash",
            status=ReceiptStatus.DRAFT,
        )
        session.add(receipt_draft)
        session.flush()
        session.add(
            ReceiptLineItem(
                id=str(uuid4()),
                receipt_id=receipt_draft.id,
                position=0,
                skr03_account_id=8400,
                amount=Decimal("50.00"),
                description="Test",
            )
        )
        session.add(ReceiptTransactionLink(receipt_id=receipt_draft.id, transaction_id=tx_draft.id))
        session.commit()

        service = DatevExportService(session)

        # Without filter: both receipts
        result_all = service.export_zip(config=datev_config, finalized_only=False)
        assert result_all.revenue_receipt_count == 2

        # With filter: only final receipt
        result_final = service.export_zip(config=datev_config, finalized_only=True)
        assert result_final.revenue_receipt_count == 1

    def should_validate_zip_and_warn_about_missing_files(self, seeded_with_source_configs, example_user, datev_config):
        """validate_zip should warn about receipts without files."""
        session = seeded_with_source_configs

        # Create receipt WITHOUT file
        receipt = Receipt(
            id=str(uuid4()),
            user_id=example_user.id,
            type=ReceiptType.EXPENSE,
            receipt_number="EXP-WARN",
            date=date(2026, 2, 15),
            counterparty="Supplier",
            # file_storage_id is None
        )
        session.add(receipt)
        session.commit()

        service = DatevExportService(session)
        result = service.validate_zip(config=datev_config)

        # Should be valid (warnings don't block)
        assert result.valid is True
        # Should have warning about missing file
        assert len(result.warnings) >= 1
        assert "EXP-WARN" in result.warnings[0] or "Belegbild fehlt" in result.warnings[0]


class TestReverseChargeDatevExport:
    """Tests for Reverse Charge (§13b) DATEV export.

    Verifies BU-Schlüssel derivation and VAT handling for RC items.
    """

    def should_use_bu_95_for_rc_without_input_tax(self, seeded_with_source_configs, example_user, datev_config):
        """RC items without input tax (Kleinunternehmer) should use BU 95."""
        from app.models.receipt_line_item import TaxRule

        session = seeded_with_source_configs
        _ensure_etsy_source_config(session)

        # Create transaction with RC fee
        transaction = Transaction(
            id="tx-rc-95",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("-10.00"),
            counterparty="Etsy Ireland",
            description="Transaction fee",
            source_config_id=ETSY_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        # Create expense receipt with RC line item (no input tax)
        receipt = Receipt(
            id=str(uuid4()),
            user_id=example_user.id,
            type=ReceiptType.EXPENSE,
            receipt_number="ETSY-FEE-001",
            date=date(2026, 2, 15),
            counterparty="Etsy Ireland",
        )
        session.add(receipt)
        session.flush()

        # Line item with RC EU no VSt (BU 95)
        line_item = ReceiptLineItem(
            id=str(uuid4()),
            receipt_id=receipt.id,
            position=0,
            skr03_account_id=3165,  # RC expense account
            amount=Decimal("10.00"),
            description="Transaction fee",
            tax_rule=TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX,
            tax_rate=Decimal("19.00"),
        )
        session.add(line_item)
        session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id))
        session.commit()

        service = DatevExportService(session)
        export = service.export(config=datev_config)

        assert export.line_item_count == 1
        row = export.rows[0]

        # BU-Schlüssel should be 95 (RC without input tax)
        bu_schluessel = row[8]
        assert bu_schluessel == "95", f"Expected BU 95, got {bu_schluessel}"

        # Booking text should contain §13b marker with VAT ID (D7)
        buchungstext = row[13]
        assert "§13b" in buchungstext, f"Booking text should contain §13b: {buchungstext}"
        assert "IE9777587C" in buchungstext, f"Booking text should contain VAT ID: {buchungstext}"

        # Kz.67 (Steuerbetrag row[31]) must be EMPTY for BU 95 — no Vorsteuerabzug
        assert row[31] == "", f"Steuerbetrag should be empty for BU 95, got '{row[31]}'"

    def should_use_bu_94_for_rc_with_input_tax(self, seeded_with_source_configs, example_user, datev_config):
        """RC items with input tax (Regelbesteuert) should use BU 94."""
        from app.models.receipt_line_item import TaxRule

        session = seeded_with_source_configs
        _ensure_etsy_source_config(session)

        transaction = Transaction(
            id="tx-rc-94",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("-10.00"),
            counterparty="Etsy Ireland",
            description="Transaction fee",
            source_config_id=ETSY_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        receipt = Receipt(
            id=str(uuid4()),
            user_id=example_user.id,
            type=ReceiptType.EXPENSE,
            receipt_number="ETSY-FEE-002",
            date=date(2026, 2, 15),
            counterparty="Etsy Ireland",
        )
        session.add(receipt)
        session.flush()

        # Line item with RC EU with VSt (BU 94)
        line_item = ReceiptLineItem(
            id=str(uuid4()),
            receipt_id=receipt.id,
            position=0,
            skr03_account_id=3125,  # RC expense account with input tax
            amount=Decimal("10.00"),
            description="Transaction fee",
            tax_rule=TaxRule.REVERSE_CHARGE_EU_WITH_INPUT_TAX,
            tax_rate=Decimal("19.00"),
        )
        session.add(line_item)
        session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id))
        session.commit()

        service = DatevExportService(session)
        export = service.export(config=datev_config)

        assert export.line_item_count == 1
        row = export.rows[0]

        # BU-Schlüssel should be 94 (RC with input tax)
        bu_schluessel = row[8]
        assert bu_schluessel == "94", f"Expected BU 94, got {bu_schluessel}"

        # Kz.67 (Steuerbetrag row[31]) must be FILLED for BU 94 — Vorsteuerabzug applies
        assert row[31] != "", "Steuerbetrag should be filled for BU 94"

    def should_calculate_19_percent_vat_for_rc(self, seeded_with_source_configs, example_user, datev_config):
        """RC items should always calculate 19% VAT."""
        from app.models.receipt_line_item import TaxRule

        session = seeded_with_source_configs
        _ensure_etsy_source_config(session)

        transaction = Transaction(
            id="tx-rc-vat",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("-100.00"),
            counterparty="Etsy Ireland",
            description="Monthly fee",
            source_config_id=ETSY_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        receipt = Receipt(
            id=str(uuid4()),
            user_id=example_user.id,
            type=ReceiptType.EXPENSE,
            receipt_number="ETSY-MONTHLY",
            date=date(2026, 2, 15),
            counterparty="Etsy Ireland",
        )
        session.add(receipt)
        session.flush()

        line_item = ReceiptLineItem(
            id=str(uuid4()),
            receipt_id=receipt.id,
            position=0,
            skr03_account_id=3165,
            amount=Decimal("100.00"),  # Net amount
            description="Monthly subscription",
            tax_rule=TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX,
            tax_rate=Decimal("19.00"),
        )
        session.add(line_item)
        session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id))
        session.commit()

        service = DatevExportService(session)
        booking_lines = service.transaction_to_booking_lines(transaction)

        assert len(booking_lines) == 1
        bl = booking_lines[0]

        # Net amount should equal gross (RC items are entered as net)
        assert bl.netto == Decimal("100.00")
        # VAT should be 19% of net
        assert bl.ust_betrag == Decimal("19.00")
        # VAT rate should be 19%
        assert bl.ust_satz == Decimal("19.00")

    def should_use_skr03_bu_for_non_rc_items(self, seeded_with_source_configs, example_user, datev_config):
        """Non-RC items should derive BU from SKR03 account, not tax_rule."""
        session = seeded_with_source_configs
        _ensure_dkb_source_config(session)

        # Ensure SKR03 account 8400 exists with bu_schluessel=3 (19% revenue)
        account_8400 = session.get(SKR03Account, 8400)
        if not account_8400:
            account_8400 = SKR03Account(
                id=8400,
                name="Erlöse 19% USt",
                category=AccountCategory.REVENUE,
                bu_schluessel=3,
            )
            session.add(account_8400)
            session.flush()

        transaction = Transaction(
            id="tx-non-rc",
            user_id=example_user.id,
            date=date(2026, 2, 15),
            amount=Decimal("119.00"),
            counterparty="Customer",
            description="Sale",
            source_config_id=DKB_SOURCE_CONFIG_ID,
        )
        session.add(transaction)
        session.flush()

        receipt = Receipt(
            id=str(uuid4()),
            user_id=example_user.id,
            type=ReceiptType.REVENUE,
            receipt_number="INV-NORMAL",
            date=date(2026, 2, 15),
            counterparty="Customer",
        )
        session.add(receipt)
        session.flush()

        # Normal line item with tax_included (NOT RC)
        line_item = ReceiptLineItem(
            id=str(uuid4()),
            receipt_id=receipt.id,
            position=0,
            skr03_account_id=8400,
            amount=Decimal("119.00"),
            description="Product sale",
            # tax_rule defaults to TAX_INCLUDED
        )
        session.add(line_item)
        session.add(ReceiptTransactionLink(receipt_id=receipt.id, transaction_id=transaction.id))
        session.commit()

        service = DatevExportService(session)
        export = service.export(config=datev_config)

        assert export.line_item_count == 1
        row = export.rows[0]

        # BU-Schlüssel should come from SKR03 account (3 = 19% revenue)
        bu_schluessel = row[8]
        assert bu_schluessel == "3", f"Expected BU 3 from SKR03 account, got {bu_schluessel}"
