"""Test configuration and fixtures."""

import os
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

# Tests run in Auth Mode (not Local Mode) — set dummy OAuth credentials.
# Use `or` (not setdefault) so an empty GOOGLE_CLIENT_ID from a dev .env.local does not leak Local Mode into tests.
os.environ["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID") or "test-google-client-id"
# Allow direct API access in tests (no proxy secret required)
os.environ.setdefault("ALLOW_INSECURE_PROXY_SECRET", "true")
# Skip Alembic migrations in lifespan — test DB uses Base.metadata.create_all
os.environ["SKIP_ALEMBIC_IN_TESTS"] = "true"
# Billbee credentials for testing (system-wide, from .env).
# Use `or` (not setdefault) so empty values passed through by docker compose do not disable the fake credentials.
os.environ["BILLBEE_API_KEY"] = os.environ.get("BILLBEE_API_KEY") or "test-billbee-api-key"
os.environ["BILLBEE_USERNAME"] = os.environ.get("BILLBEE_USERNAME") or "user@billbee.io"
os.environ["BILLBEE_PASSWORD"] = os.environ.get("BILLBEE_PASSWORD") or "secret123"

# Derive test database URL from DATABASE_URL (already set by docker-compose.yml)
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not _DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set (tests run inside Docker)")

# Replace the database name with a _test suffix
# DATABASE_URL format: postgresql://user:pass@host:port/dbname
_BASE_URL = _DATABASE_URL.rsplit("/", 1)[0]
_MAIN_DB = _DATABASE_URL.rsplit("/", 1)[1]
_TEST_DB = f"{_MAIN_DB}_test"
_TEST_DATABASE_URL = f"{_BASE_URL}/{_TEST_DB}"

# Override DATABASE_URL so app code picks up the test database
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL

from app.database import Base, get_db  # noqa: E402
from app.models import (  # noqa: E402, F401
    AccountingPattern,
    ExportLog,
    ImportLog,
    SiteSettings,
    SKR03Account,
    Transaction,
    User,
)


@pytest.fixture(scope="session")
def database_engine():
    """Create test database and engine against PostgreSQL."""
    # Connect to default DB to create/drop the test database
    admin_engine = create_engine(f"{_BASE_URL}/{_MAIN_DB}", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        # Terminate existing connections to test DB
        connection.execute(text(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{_TEST_DB}' AND pid <> pg_backend_pid()"))
        connection.execute(text(f"DROP DATABASE IF EXISTS {_TEST_DB}"))
        connection.execute(text(f"CREATE DATABASE {_TEST_DB}"))
    admin_engine.dispose()

    # Create engine for the test database
    engine = create_engine(_TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
    yield engine

    # Cleanup: drop test database
    engine.dispose()
    admin_engine = create_engine(f"{_BASE_URL}/{_MAIN_DB}", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{_TEST_DB}' AND pid <> pg_backend_pid()"))
        connection.execute(text(f"DROP DATABASE IF EXISTS {_TEST_DB}"))
    admin_engine.dispose()


def _auto_assign_check_account_id(session, _flush_context, _instances):
    """Auto-assign check_account_id for TransactionSourceConfig in tests.

    Finds the next free ID in 1200-1288 range so tests don't need to
    specify check_account_id explicitly on every source config creation.
    """
    from app.models.source import TransactionSourceConfig

    for obj in session.new:
        if isinstance(obj, TransactionSourceConfig) and obj.check_account_id is None:
            used = {s.check_account_id for s in session.new if isinstance(s, TransactionSourceConfig) and s.check_account_id is not None}
            # Also check already-persisted sources in this session
            existing = session.execute(select(TransactionSourceConfig.check_account_id)).scalars().all()
            used.update(existing)
            for candidate in range(1200, 1289):
                if candidate not in used:
                    obj.check_account_id = candidate
                    break


@pytest.fixture
def database_session(database_engine):
    """Provide a transactional database session for testing.

    Each test runs inside a transaction that is rolled back afterwards,
    so tests are isolated without needing to recreate tables.
    """

    connection = database_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    event.listen(session, "before_flush", _auto_assign_check_account_id)

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def seeded_session(database_session):
    """Database session with SKR03 seed data, SiteSettings, and a Billbee OMS provider."""
    from app.models.oms_provider import OmsProviderRecord, OmsProviderType
    from app.seed import seed_site_settings, seed_skr03_accounts, seed_system_user

    seed_skr03_accounts(database_session)
    seed_site_settings(database_session)
    seed_system_user(database_session)

    from sqlalchemy import select

    existing = database_session.scalar(select(OmsProviderRecord).where(OmsProviderRecord.type == OmsProviderType.BILLBEE))
    if existing is None:
        database_session.add(OmsProviderRecord(type=OmsProviderType.BILLBEE, display_name="Billbee", is_active=True))
        database_session.flush()
    return database_session


@pytest.fixture
def oms_provider_record(seeded_session):
    """The seeded Billbee OmsProviderRecord."""
    from app.models.oms_provider import OmsProviderRecord, OmsProviderType
    from sqlalchemy import select

    return seeded_session.scalar(select(OmsProviderRecord).where(OmsProviderRecord.type == OmsProviderType.BILLBEE))


@pytest.fixture
def example_user(database_session):
    """Create an example user for testing."""
    user = User(
        id="test-user-id",
        provider_id="test-user-id",
        provider_type="google",
        email="test@example.com",
        name="Test User",
    )
    database_session.add(user)
    database_session.commit()
    return user


# --- TestClient fixtures for integration tests ---

AUTH_HEADERS = {
    "x-user-id": "test-user-id",
    "x-user-name": "Test User",
    "x-user-email": "test@example.com",
}


@pytest.fixture
def api_client(database_session, example_user, seeded_session):
    """FastAPI TestClient with DB session override and auth headers.

    Provides a client that uses the transactional test session (rolled back
    after each test) and includes the seeded SKR03 accounts + example user.
    """
    from app.main import app
    from fastapi.testclient import TestClient

    def _override_get_db():
        yield database_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


TEST_SOURCE_CONFIG_ID = "a0000000-0000-0000-0000-000000000001"  # Etsy system source


def _ensure_test_source_config(session) -> str:
    """Ensure a test source config exists, return its ID."""
    from app.models.source import SourceType, TransactionSourceConfig

    existing = session.get(TransactionSourceConfig, TEST_SOURCE_CONFIG_ID)
    if not existing:
        session.add(
            TransactionSourceConfig(
                id=TEST_SOURCE_CONFIG_ID,
                user_id=None,
                name="Etsy",
                type=SourceType.CSV_PARSER,
                check_account_id=1288,
            )
        )
        session.flush()
    return TEST_SOURCE_CONFIG_ID


def _create_example_transaction(
    session,
    *,
    user_id: str = "test-user-id",
    amount: Decimal = Decimal("100.00"),
    counterparty: str = "Example Shop",
    description: str = "Payment",
    source_config_id: str | None = None,
    transaction_date: date = date(2026, 1, 15),
    is_private: bool = False,
) -> Transaction:
    """Create a transaction in the test database."""
    from uuid import uuid4

    if source_config_id is None:
        source_config_id = _ensure_test_source_config(session)

    transaction = Transaction(
        id=str(uuid4()),
        user_id=user_id,
        date=transaction_date,
        amount=amount,
        counterparty=counterparty,
        description=description,
        source_config_id=source_config_id,
        is_private=is_private,
    )
    session.add(transaction)
    session.flush()
    return transaction
