"""🌱 Tests for SKR03 seed data."""

from app.models.skr03 import SKR03Account
from app.seed import seed_skr03_accounts
from sqlalchemy import select


def should_seed_49_accounts(database_session):
    count = seed_skr03_accounts(database_session)
    database_session.flush()

    assert count == 49

    total = database_session.execute(select(SKR03Account)).scalars().all()
    assert len(total) == 49


def should_be_idempotent(database_session):
    seed_skr03_accounts(database_session)
    database_session.flush()

    second_count = seed_skr03_accounts(database_session)
    database_session.flush()

    assert second_count == 0

    total = database_session.execute(select(SKR03Account)).scalars().all()
    assert len(total) == 49


def should_backfill_bu_schluessel(database_session):
    # First seed to get all accounts
    seed_skr03_accounts(database_session)
    database_session.flush()

    # Pick an account and clear its bu_schluessel
    account = database_session.execute(select(SKR03Account).where(SKR03Account.bu_schluessel.is_not(None))).scalars().first()

    assert account is not None, "Expected at least one account with bu_schluessel set"

    expected_account_id = account.id
    account.bu_schluessel = None
    database_session.flush()

    # Re-seed should backfill the cleared bu_schluessel
    seed_skr03_accounts(database_session)
    database_session.flush()

    database_session.refresh(account)
    assert account.bu_schluessel is not None, f"bu_schluessel for account {expected_account_id} should be backfilled"
