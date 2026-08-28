"""PayPal sync service — fetches transactions via API and imports them."""

import logging
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.paypal_sync_log import PayPalSyncLog, PayPalSyncStatus
from app.models.source import TransactionSourceConfig
from app.models.sync_common import SyncResult
from app.models.transaction import Transaction
from app.services.paypal_client import PayPalApiError, fetch_all_transactions

logger = logging.getLogger(__name__)

# PayPal event codes to import (balance-affecting business transactions)
IMPORT_EVENT_CODES = {"T0006", "T0007", "T0013", "T1107"}

# PayPal event codes to skip (internal operations)
SKIP_EVENT_CODES = {"T0200", "T0400"}


def _get_paypal_source_config(database: Session) -> TransactionSourceConfig | None:
    """Get the PayPal TransactionSourceConfig."""
    statement = select(TransactionSourceConfig).where(
        TransactionSourceConfig.name == "PayPal",
    )
    return database.scalars(statement).first()


def _is_duplicate(database: Session, source_config_id: str, source_reference: str) -> bool:
    """Check if a transaction with same source_config + source_reference already exists."""
    statement = select(Transaction.id).where(
        and_(
            Transaction.source_config_id == source_config_id,
            Transaction.source_reference == source_reference,
            Transaction.deleted_at.is_(None),
        )
    )
    return database.execute(statement).first() is not None


def _map_transaction(
    user_id: str,
    source_config_id: str,
    transaction_detail: dict,
) -> Transaction | None:
    """Map a PayPal API transaction detail to a Transaction model.

    Returns None if the transaction should be skipped.
    """
    transaction_info = transaction_detail.get("transaction_info", {})

    # Check event code
    event_code = transaction_info.get("transaction_event_code", "")
    if event_code in SKIP_EVENT_CODES:
        return None
    if event_code not in IMPORT_EVENT_CODES:
        return None

    # Only import successful transactions
    if transaction_info.get("transaction_status") != "S":
        return None

    transaction_id = transaction_info.get("transaction_id", "")
    if not transaction_id:
        return None

    # Parse amount
    amount_info = transaction_info.get("transaction_amount", {})
    currency_code = amount_info.get("currency_code", "EUR")
    amount_value = Decimal(str(amount_info.get("value", "0")))

    # Parse date
    date_str = transaction_info.get("transaction_initiation_date", "")
    transaction_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()

    # Build counterparty from payer info
    payer_info = transaction_detail.get("payer_info", {})
    payer_name = payer_info.get("payer_name", {}).get("alternate_full_name", "")
    payer_email = payer_info.get("email_address", "")
    counterparty = payer_name or payer_email or "PayPal"

    # Build description from subject/note
    subject = transaction_info.get("transaction_subject", "")
    note = transaction_info.get("transaction_note", "")
    description = subject or note or f"PayPal {event_code}"

    # Currency handling: non-EUR → store original currency fields; EUR → leave NULL
    original_currency = None
    original_amount = None
    exchange_rate = None

    if currency_code != "EUR":
        original_currency = currency_code
        original_amount = amount_value
        # PayPal doesn't always provide exchange rate in transaction_info directly.
        # The EUR amount comes as the transaction amount when balance is in EUR.
        # For now, we store the original and the EUR equivalent will be the `amount` field.
        # The caller must provide the EUR amount from the conversion if available.
        exchange_rate = None

    return Transaction(
        id=str(uuid4()),
        user_id=user_id,
        date=transaction_date,
        amount=amount_value if currency_code == "EUR" else amount_value,
        counterparty=counterparty,
        description=description,
        source_config_id=source_config_id,
        source_reference=transaction_id,
        original_currency=original_currency,
        original_amount=original_amount,
        exchange_rate=exchange_rate,
    )


def _create_fee_transaction(
    user_id: str,
    source_config_id: str,
    transaction_detail: dict,
) -> Transaction | None:
    """Create a separate fee transaction from a PayPal transaction.

    Returns None if fee is 0 or missing.
    """
    transaction_info = transaction_detail.get("transaction_info", {})
    fee_info = transaction_info.get("fee_amount", {})

    if not fee_info:
        return None

    fee_value = Decimal(str(fee_info.get("value", "0")))
    if fee_value == 0:
        return None

    transaction_id = transaction_info.get("transaction_id", "")
    date_str = transaction_info.get("transaction_initiation_date", "")
    transaction_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()

    return Transaction(
        id=str(uuid4()),
        user_id=user_id,
        date=transaction_date,
        amount=fee_value,
        counterparty="PayPal",
        description="PayPal Gebühr",
        source_config_id=source_config_id,
        source_reference=f"{transaction_id}_FEE",
    )


def sync(
    database: Session,
    user_id: str,
    start_date: datetime,
    end_date: datetime,
) -> SyncResult:
    """Sync PayPal transactions for a date range.

    1. Fetches transactions via PayPal API
    2. Filters by status and event code
    3. Maps to Transaction model, creates fee Transactions
    4. Deduplicates by source_reference
    5. Creates PayPalSyncLog entry

    Partial failure: already-imported transactions are kept on API error.
    """
    errors: list[str] = []
    imported_count = 0
    skipped_count = 0
    fee_count = 0
    fetched_count = 0

    # Get PayPal source config (required for source_config_id)
    paypal_source = _get_paypal_source_config(database)
    if paypal_source is None:
        sync_log = PayPalSyncLog(
            id=str(uuid4()),
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            fetched_count=0,
            imported_count=0,
            fee_count=0,
            status=PayPalSyncStatus.FAILED,
            error_message="PayPal source config not found. Run seed to create system sources.",
        )
        database.add(sync_log)
        database.commit()
        return SyncResult(
            imported_count=0,
            skipped_count=0,
            fee_count=0,
            sync_log_id=sync_log.id,
            errors=["PayPal source config not found"],
        )

    source_config_id = paypal_source.id

    try:
        raw_transactions = fetch_all_transactions(start_date, end_date)
        fetched_count = len(raw_transactions)
    except PayPalApiError as error:
        sync_log = PayPalSyncLog(
            id=str(uuid4()),
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            fetched_count=0,
            imported_count=0,
            fee_count=0,
            status=PayPalSyncStatus.FAILED,
            error_message=str(error),
        )
        database.add(sync_log)
        database.commit()
        return SyncResult(
            imported_count=0,
            skipped_count=0,
            fee_count=0,
            sync_log_id=sync_log.id,
            errors=[str(error)],
        )

    for raw_transaction in raw_transactions:
        transaction = _map_transaction(user_id, source_config_id, raw_transaction)
        if transaction is None:
            skipped_count += 1
            continue

        # Deduplicate (source_reference is always set by _map_transaction)
        if transaction.source_reference is None:
            skipped_count += 1
            continue
        if _is_duplicate(database, source_config_id, transaction.source_reference):
            skipped_count += 1
            continue

        database.add(transaction)
        imported_count += 1

        # Create fee transaction
        fee_transaction = _create_fee_transaction(user_id, source_config_id, raw_transaction)
        if fee_transaction is not None and fee_transaction.source_reference is not None:
            if not _is_duplicate(database, source_config_id, fee_transaction.source_reference):
                database.add(fee_transaction)
                fee_count += 1

    status = PayPalSyncStatus.SUCCESS if not errors else PayPalSyncStatus.PARTIAL
    sync_log = PayPalSyncLog(
        id=str(uuid4()),
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        fetched_count=fetched_count,
        imported_count=imported_count,
        fee_count=fee_count,
        status=status,
        error_message="; ".join(errors) if errors else None,
    )
    database.add(sync_log)
    database.commit()

    logger.info(
        "PayPal sync complete: %d fetched, %d imported, %d fees, %d skipped",
        fetched_count,
        imported_count,
        fee_count,
        skipped_count,
    )

    return SyncResult(
        imported_count=imported_count,
        skipped_count=skipped_count,
        fee_count=fee_count,
        sync_log_id=sync_log.id,
        errors=errors,
    )
