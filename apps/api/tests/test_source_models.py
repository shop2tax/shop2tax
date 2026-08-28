"""Tests for TransactionSourceConfig and CsvMappingProfile models."""

from datetime import date
from decimal import Decimal

import pytest
from app.models.source import CsvMappingProfile, SourceType, TransactionSourceConfig
from app.models.transaction import Transaction
from app.models.user import User


@pytest.fixture
def example_user(database_session):
    """Create an example user for testing."""
    user = User(
        id="test-user-id",
        provider_id="test-google-id",
        provider_type="google",
        email="test@example.com",
        name="Test User",
    )
    database_session.add(user)
    database_session.flush()
    return user


@pytest.fixture
def system_source(database_session):
    """Create a system marketplace source."""
    source = TransactionSourceConfig(
        id="system-etsy-id",
        user_id=None,
        name="Etsy",
        type=SourceType.CSV_PARSER,
        check_account_id=1200,
    )
    database_session.add(source)
    database_session.flush()
    return source


@pytest.fixture
def bank_source(database_session, example_user):
    """Create a user-owned bank source."""
    source = TransactionSourceConfig(
        id="user-bank-id",
        user_id=example_user.id,
        name="DKB",
        type=SourceType.CSV_MAPPING,
        check_account_id=1201,
    )
    database_session.add(source)
    database_session.flush()
    return source


class TestTransactionSourceConfig:
    def should_create_system_source_without_user(self, database_session, system_source):
        result = database_session.get(TransactionSourceConfig, "system-etsy-id")
        assert result is not None
        assert result.name == "Etsy"
        assert result.type == SourceType.CSV_PARSER
        assert result.user_id is None

    def should_create_bank_source_with_user(self, database_session, bank_source, example_user):
        result = database_session.get(TransactionSourceConfig, "user-bank-id")
        assert result is not None
        assert result.name == "DKB"
        assert result.type == SourceType.CSV_MAPPING
        assert result.user_id == example_user.id

    def should_link_transaction_to_source_config(self, database_session, bank_source, example_user):
        transaction = Transaction(
            user_id=example_user.id,
            date=date(2026, 1, 15),
            amount=Decimal("100.00"),
            counterparty="Shop",
            description="Payment",
            source_config_id=bank_source.id,
        )
        database_session.add(transaction)
        database_session.flush()

        loaded = database_session.get(Transaction, transaction.id)
        assert loaded.source_config_id == bank_source.id
        assert loaded.source_config.name == "DKB"

    def should_store_import_hash(self, database_session, bank_source, example_user):
        transaction = Transaction(
            user_id=example_user.id,
            date=date(2026, 1, 15),
            amount=Decimal("-42.50"),
            counterparty="Amazon",
            description="Order",
            source_config_id=bank_source.id,
            import_hash="abc123def456",
        )
        database_session.add(transaction)
        database_session.flush()

        loaded = database_session.get(Transaction, transaction.id)
        assert loaded.import_hash == "abc123def456"

    def should_list_transactions_for_source(self, database_session, bank_source, example_user):
        for i in range(3):
            database_session.add(
                Transaction(
                    user_id=example_user.id,
                    date=date(2026, 1, i + 1),
                    amount=Decimal("10.00"),
                    counterparty=f"Shop {i}",
                    description="Payment",
                    source_config_id=bank_source.id,
                )
            )
        database_session.flush()

        loaded = database_session.get(TransactionSourceConfig, bank_source.id)
        assert len(loaded.transactions) == 3


class TestCsvMappingProfile:
    def should_create_mapping_profile(self, database_session, bank_source, example_user):
        mapping = CsvMappingProfile(
            user_id=example_user.id,
            source_id=bank_source.id,
            name="DKB Standard",
            delimiter=";",
            encoding="utf-8-sig",
            has_header=True,
            skip_rows=4,
            date_format="%d.%m.%y",
            amount_format="german",
            column_date="Buchungsdatum",
            column_amount="Betrag (EUR)",
            column_counterparty="Auftraggeber / Begünstigter",
            column_description="Verwendungszweck",
        )
        database_session.add(mapping)
        database_session.flush()

        loaded = database_session.get(CsvMappingProfile, mapping.id)
        assert loaded.delimiter == ";"
        assert loaded.skip_rows == 4
        assert loaded.column_amount == "Betrag (EUR)"

    def should_enforce_unique_mapping_per_source(self, database_session, bank_source, example_user):
        mapping1 = CsvMappingProfile(
            user_id=example_user.id,
            source_id=bank_source.id,
            column_date="Date",
            column_counterparty="Name",
            column_description="Desc",
        )
        database_session.add(mapping1)
        database_session.flush()

        mapping2 = CsvMappingProfile(
            user_id=example_user.id,
            source_id=bank_source.id,
            column_date="Datum",
            column_counterparty="Name2",
            column_description="Desc2",
        )
        database_session.add(mapping2)
        with pytest.raises(Exception):  # IntegrityError from unique constraint
            database_session.flush()

    def should_link_mapping_to_source(self, database_session, bank_source, example_user):
        mapping = CsvMappingProfile(
            user_id=example_user.id,
            source_id=bank_source.id,
            column_date="Date",
            column_counterparty="Name",
            column_description="Desc",
        )
        database_session.add(mapping)
        database_session.flush()

        loaded_source = database_session.get(TransactionSourceConfig, bank_source.id)
        assert loaded_source.mapping_profile is not None
        assert loaded_source.mapping_profile.id == mapping.id
