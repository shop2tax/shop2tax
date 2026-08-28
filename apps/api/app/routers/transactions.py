"""Transactions router."""

import logging
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, String, and_, cast, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.exceptions import raise_not_found
from app.core.pagination import PaginationParams, paginate_query
from app.core.sql import escape_like
from app.database import get_db
from app.deps import CurrentUser, get_current_user
from app.models.import_log import ImportLog
from app.models.receipt_transaction_link import ReceiptTransactionLink
from app.models.transaction import Transaction
from app.schemas.transaction import (
    AutoLinkRequest,
    AutoLinkResponse,
    ConfirmPayoutMatchRequest,
    ConfirmPayoutMatchResponse,
    FindMatchingReceiptsRequest,
    FindMatchingReceiptsResponse,
    MarkPrivateRequest,
    MatchingReceiptSummary,
    PayoutSuggestionsResponse,
    TransactionCreate,
    TransactionImportRequest,
    TransactionImportResponse,
    TransactionListResponse,
    TransactionResponse,
    TransactionStatus,
    TransactionUpdate,
    TransferLinkRequest,
    TransferSuggestion,
)
from app.services.receipt_service import auto_link_by_oms_order_id
from app.services.response_builders import build_transaction_response

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])

logger = logging.getLogger(__name__)


def _receipt_amount_subquery():
    """Subquery: total receipt line item amount per transaction."""
    from app.models.receipt_line_item import ReceiptLineItem

    return (
        select(
            ReceiptTransactionLink.transaction_id,
            func.count(func.distinct(ReceiptTransactionLink.receipt_id)).label("receipt_count"),
            func.coalesce(func.sum(ReceiptLineItem.amount), 0).label("receipt_amount"),
        )
        .join(ReceiptLineItem, ReceiptLineItem.receipt_id == ReceiptTransactionLink.receipt_id)
        .group_by(ReceiptTransactionLink.transaction_id)
        .subquery()
    )


def _apply_status_filter(query, status: TransactionStatus):
    """Apply SQL-level status filter using receipt aggregation subquery.

    Mirrors the logic in _compute_transaction_status (response_builders.py).
    """
    if status == TransactionStatus.PRIVATE:
        return query.where(Transaction.is_private.is_(True))

    if status == TransactionStatus.INTERNAL:
        return query.where(Transaction.is_internal_transfer.is_(True))

    # For receipt-based statuses, exclude PRIVATE and INTERNAL first
    query = query.where(
        Transaction.is_private.is_(False),
        Transaction.is_internal_transfer.is_(False),
    )

    receipt_sub = _receipt_amount_subquery()

    if status == TransactionStatus.OPEN:
        # No linked receipts
        return query.where(~Transaction.id.in_(select(ReceiptTransactionLink.transaction_id)))

    # Join the subquery for statuses that need receipt amounts
    query = query.join(receipt_sub, receipt_sub.c.transaction_id == Transaction.id)

    if status == TransactionStatus.ASSIGNED:
        # Has receipts but open_amount > 0
        return query.where(receipt_sub.c.receipt_amount < func.abs(Transaction.amount))

    if status == TransactionStatus.AUTOMATIC:
        # Fully booked + OMS-matched
        return query.where(
            receipt_sub.c.receipt_amount >= func.abs(Transaction.amount),
            Transaction.oms_order_id.isnot(None),
        )

    if status == TransactionStatus.BOOKED:
        # Fully booked + no OMS order
        return query.where(
            receipt_sub.c.receipt_amount >= func.abs(Transaction.amount),
            Transaction.oms_order_id.is_(None),
        )

    return query


def _build_base_query() -> Select[tuple[Transaction]]:
    """Build base query for transactions with eager loading.

    Includes receipt_links → receipt → line_items for status/open_amount computation.
    """
    from app.models.receipt import Receipt

    return (
        select(Transaction)
        .where(Transaction.deleted_at.is_(None))
        .options(
            joinedload(Transaction.receipt_links).joinedload(ReceiptTransactionLink.receipt).joinedload(Receipt.line_items),
        )
    )


def _load_transaction_or_404(database: Session, transaction_id: str) -> Transaction:
    """Reload a transaction with relationships, raising 404 if it no longer exists."""
    transaction = database.scalars(_build_base_query().where(Transaction.id == transaction_id)).first()
    if transaction is None:
        raise_not_found("Transaction", transaction_id)
    return transaction


@router.get("", response_model=TransactionListResponse)
def list_transactions(
    pagination: PaginationParams = Depends(),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
    source_config_id: str | None = Query(None, description="Filter by source config ID"),
    status: TransactionStatus | None = Query(None, description="Filter by computed status"),
    is_private: bool | None = Query(None, description="Filter by private flag"),
    date_from: date_type | None = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: date_type | None = Query(None, description="Filter to date (YYYY-MM-DD)"),
    search: str | None = Query(None, description="Search in counterparty/description"),
    search_field: str | None = Query(None, description="Restrict search to: counterparty, description, amount"),
    skr03_account_id: int | None = Query(None, description="Filter by SKR03 account on linked receipts"),
    marketplace_category: str | None = Query(None, description="Filter by extra_data.marketplace_category (comma-separated: fee,marketing)"),
) -> TransactionListResponse:
    """List transactions with filtering and pagination.

    Status is computed from linked receipts:
    - OPEN: No linked receipts
    - ASSIGNED: Has receipts but open_amount > 0
    - BOOKED: Fully covered by receipts (open_amount = 0)
    - AUTOMATIC: Auto-linked via OMS
    - PRIVATE: Marked as private
    - INTERNAL: Internal transfer (Geldbewegung)
    """

    query = _build_base_query()

    # Apply database filters
    if source_config_id:
        query = query.where(Transaction.source_config_id == source_config_id)
    if is_private is not None:
        query = query.where(Transaction.is_private == is_private)
    if date_from:
        query = query.where(Transaction.date >= date_from)
    if date_to:
        query = query.where(Transaction.date <= date_to)
    if search:
        search_pattern = f"%{escape_like(search)}%"
        if search_field == "counterparty":
            query = query.where(Transaction.counterparty.ilike(search_pattern))
        elif search_field == "description":
            query = query.where(Transaction.description.ilike(search_pattern))
        elif search_field == "amount":
            query = query.where(cast(Transaction.amount, String).ilike(search_pattern))
        else:
            query = query.where(Transaction.counterparty.ilike(search_pattern) | Transaction.description.ilike(search_pattern))

    # Filter by SKR03 account: transaction has a linked receipt with a line item using this account
    if skr03_account_id is not None:
        from app.models.receipt_line_item import ReceiptLineItem

        skr03_subquery = (
            select(ReceiptTransactionLink.transaction_id)
            .join(ReceiptLineItem, ReceiptLineItem.receipt_id == ReceiptTransactionLink.receipt_id)
            .where(ReceiptLineItem.skr03_account_id == skr03_account_id)
        )
        query = query.where(Transaction.id.in_(skr03_subquery))

    # Filter by marketplace category (extra_data JSONB)
    if marketplace_category:
        categories = [c.strip() for c in marketplace_category.split(",")]
        query = query.where(Transaction.extra_data["marketplace_category"].astext.in_(categories))

    # Filter by computed status at SQL level
    if status is not None:
        query = _apply_status_filter(query, status)

    # Apply deterministic ordering (date desc, then id as tiebreaker)
    query = query.order_by(Transaction.date.desc(), Transaction.id.desc())

    items, total = paginate_query(database, query, pagination)
    responses = [build_transaction_response(t) for t in items]

    return TransactionListResponse(
        items=responses,
        total=total,
    )


# --- Payout↔Bank Matching Endpoints ---
# NOTE: These must be defined BEFORE /{transaction_id} to avoid path parameter conflicts.


@router.get("/payout-suggestions")
def get_payout_suggestions(
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
    days_back: int = Query(30, description="How many days back to search for unmatched deposits"),
) -> PayoutSuggestionsResponse:
    """Find unmatched bank deposits and suggest matching marketplace payouts.

    After bank CSV import, this endpoint helps match incoming deposits
    to outgoing marketplace payouts (Etsy, Amazon, PayPal, etc.).

    Uses SourceType to distinguish bank vs marketplace — NOT hardcoded account IDs.

    Matching criteria:
    - Amount must match exactly (±0.02€) — required
    - Date within ±3 days — score boost

    The matched pairs can then be linked as internal transfers (Geldtransit).
    """
    from app.models.source import SourceType, TransactionSourceConfig
    from app.schemas.transaction import BankDepositWithSuggestions, PayoutSuggestion

    cutoff_date = date_type.today() - timedelta(days=days_back)

    # Bank sources: CSV_MAPPING (user-configured bank CSVs)
    bank_source_types = {SourceType.CSV_MAPPING}
    # Marketplace sources: MARKETPLACE_MAPPING + API_SYNC (PayPal)
    marketplace_source_types = {SourceType.MARKETPLACE_MAPPING, SourceType.API_SYNC}

    # Find unmatched bank deposits (positive amounts on bank sources, not linked)
    bank_deposits_query = (
        select(Transaction)
        .join(TransactionSourceConfig)
        .options(joinedload(Transaction.source_config))
        .where(
            Transaction.deleted_at.is_(None),
            Transaction.amount > 0,  # Deposits are positive
            TransactionSourceConfig.type.in_(bank_source_types),
            Transaction.linked_transfer_id.is_(None),  # Not already matched
            Transaction.date >= cutoff_date,
        )
        .order_by(Transaction.date.desc())
    )
    bank_deposits = database.scalars(bank_deposits_query).unique().all()

    # Find all marketplace payouts (negative amounts on marketplace sources)
    # that are not yet matched to a bank deposit
    payout_query = (
        select(Transaction)
        .join(TransactionSourceConfig)
        .options(joinedload(Transaction.source_config))
        .where(
            Transaction.deleted_at.is_(None),
            Transaction.amount < 0,  # Payouts are negative (outflow from clearing account)
            TransactionSourceConfig.type.in_(marketplace_source_types),
            Transaction.linked_transfer_id.is_(None),  # Not already matched
            Transaction.is_internal_transfer.is_(True),  # Payouts are internal transfers
        )
    )
    all_payouts = database.scalars(payout_query).unique().all()

    # Match deposits to payouts
    deposits_with_suggestions: list[BankDepositWithSuggestions] = []

    for deposit in bank_deposits:
        suggestions: list[PayoutSuggestion] = []
        deposit_amount = abs(deposit.amount)

        for payout in all_payouts:
            payout_amount = abs(payout.amount)
            amount_diff = abs(deposit_amount - payout_amount)

            # Amount must match within ±0.02€
            if amount_diff > Decimal("0.02"):
                continue

            # Calculate score: start at 0.5, boost for date proximity
            score = 0.5

            # Date proximity scoring (±3 days)
            date_diff = abs((deposit.date - payout.date).days)
            if date_diff == 0:
                score += 0.5
            elif date_diff == 1:
                score += 0.4
            elif date_diff == 2:
                score += 0.3
            elif date_diff == 3:
                score += 0.2
            # date_diff > 3 gets no boost

            suggestions.append(
                PayoutSuggestion(
                    payout_id=payout.id,
                    payout_date=payout.date,
                    payout_amount=payout.amount,
                    payout_counterparty=payout.counterparty,
                    payout_source_name=payout.source_config.name if payout.source_config else "Unknown",
                    payout_check_account=payout.source_config.check_account_id if payout.source_config else 0,
                    match_score=round(score, 2),
                )
            )

        # Sort suggestions by score descending
        suggestions.sort(key=lambda s: s.match_score, reverse=True)

        # Only include deposits with at least one suggestion
        if suggestions:
            deposits_with_suggestions.append(
                BankDepositWithSuggestions(
                    bank_transaction_id=deposit.id,
                    bank_date=deposit.date,
                    bank_amount=deposit.amount,
                    bank_counterparty=deposit.counterparty,
                    bank_description=deposit.description,
                    bank_source_name=deposit.source_config.name if deposit.source_config else "Bank",
                    suggestions=suggestions[:5],  # Top 5 suggestions per deposit
                )
            )

    return PayoutSuggestionsResponse(
        deposits=deposits_with_suggestions,
        deposit_count=len(deposits_with_suggestions),
    )


@router.post("/confirm-payout-match")
def confirm_payout_match(
    data: ConfirmPayoutMatchRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> ConfirmPayoutMatchResponse:
    """Confirm a payout↔bank match, creating an internal transfer link.

    Links the bank deposit and marketplace payout as an internal transfer
    (Geldtransit-Buchung: marketplace clearing account → bank).

    Both transactions will be marked as is_internal_transfer=True and
    linked via linked_transfer_id.
    """
    # Get bank transaction
    bank_tx = database.scalars(
        select(Transaction)
        .options(joinedload(Transaction.source_config))
        .where(
            Transaction.id == data.bank_transaction_id,
            Transaction.deleted_at.is_(None),
        )
    ).first()

    if not bank_tx:
        raise_not_found("Bank transaction", data.bank_transaction_id)

    # Get payout transaction
    payout_tx = database.scalars(
        select(Transaction)
        .options(joinedload(Transaction.source_config))
        .where(
            Transaction.id == data.payout_transaction_id,
            Transaction.deleted_at.is_(None),
        )
    ).first()

    if not payout_tx:
        raise_not_found("Payout transaction", data.payout_transaction_id)

    # Validate: bank transaction should be a deposit (positive)
    if bank_tx.amount <= 0:
        raise HTTPException(status_code=400, detail="Bank transaction must be a deposit (positive amount)")

    # Validate: payout transaction should be negative
    if payout_tx.amount >= 0:
        raise HTTPException(status_code=400, detail="Payout transaction must have negative amount")

    # Validate: neither should already be linked
    if bank_tx.linked_transfer_id:
        raise HTTPException(status_code=400, detail="Bank transaction is already linked to another transfer")
    if payout_tx.linked_transfer_id:
        raise HTTPException(status_code=400, detail="Payout transaction is already linked to another transfer")

    # Validate: amounts should match within ±0.02€
    amount_diff = abs(abs(bank_tx.amount) - abs(payout_tx.amount))
    if amount_diff > Decimal("0.02"):
        raise HTTPException(
            status_code=400,
            detail=f"Amount mismatch: bank {bank_tx.amount}, payout {payout_tx.amount} (diff: {amount_diff})",
        )

    # Link as internal transfer (bidirectional)
    bank_tx.linked_transfer_id = payout_tx.id
    bank_tx.is_internal_transfer = True

    payout_tx.linked_transfer_id = bank_tx.id
    # payout_tx.is_internal_transfer should already be True from marketplace parser

    database.commit()

    payout_name = payout_tx.source_config.name if payout_tx.source_config else "Marketplace"

    return ConfirmPayoutMatchResponse(
        bank_transaction_id=bank_tx.id,
        payout_transaction_id=payout_tx.id,
        message=f"Geldtransit verknüpft: {payout_name} → Bank ({abs(bank_tx.amount)}€)",
    )


@router.get("/{transaction_id}", response_model=TransactionResponse)
def get_transaction(
    transaction_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> TransactionResponse:
    """Get a single transaction by ID."""
    transaction = _load_transaction_or_404(database, transaction_id)

    return build_transaction_response(transaction)


@router.get("/{transaction_id}/receipt-suggestions")
def get_receipt_suggestions_for_transaction(
    transaction_id: str,
    receipt_type: str | None = Query(None, description="Filter by receipt type (revenue/expense)"),
    search: str | None = Query(None, description="Counterparty text search"),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> list[dict]:
    """Get receipt suggestions for a transaction (reverse lookup).

    Returns receipts that match this payment based on amount and date proximity.
    """
    from app.services.receipt_matching import suggest_receipts_for_payment

    suggestions = suggest_receipts_for_payment(
        database,
        transaction_id,
        receipt_type=receipt_type,
        search=search,
    )

    return [
        {
            "id": s.id,
            "receipt_number": s.receipt_number,
            "type": s.receipt_type,
            "counterparty": s.receipt_counterparty,
            "amount": str(s.amount),
            "date": s.date,
            "confidence": s.confidence,
            "reasons": s.reasons or [],
        }
        for s in suggestions
    ]


@router.post("", response_model=TransactionResponse, status_code=201)
def create_transaction(
    data: TransactionCreate,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> TransactionResponse:
    """Create a new transaction."""
    from app.models.source import TransactionSourceConfig

    # Validate source_config_id exists
    source_config = database.scalars(
        select(TransactionSourceConfig).where(
            TransactionSourceConfig.id == data.source_config_id,
        )
    ).first()
    if not source_config:
        raise_not_found("Source config", data.source_config_id)

    transaction = Transaction(
        id=str(uuid4()),
        user_id=user.id,
        date=data.date,
        amount=data.amount,
        counterparty=data.counterparty,
        description=data.description,
        source_config_id=data.source_config_id,
        source_reference=data.source_reference,
        notes=data.notes,
        is_private=data.is_private,
    )

    database.add(transaction)
    transaction_id = transaction.id
    database.commit()

    return build_transaction_response(_load_transaction_or_404(database, transaction_id))


@router.patch("/{transaction_id}", response_model=TransactionResponse)
def update_transaction(
    transaction_id: str,
    data: TransactionUpdate,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> TransactionResponse:
    """Update a transaction."""
    transaction = _load_transaction_or_404(database, transaction_id)

    # Block financial field changes on transactions with locked receipts
    update_data = data.model_dump(exclude_unset=True)
    immutable_fields = {"amount", "date"}
    if update_data.keys() & immutable_fields:
        has_locked = any(link.receipt.is_locked for link in transaction.receipt_links if link.receipt)
        if has_locked:
            raise HTTPException(
                status_code=403,
                detail="Cannot modify amount/date on transactions linked to locked receipts (GoBD)",
            )

    for key, value in update_data.items():
        setattr(transaction, key, value)

    database.commit()
    database.refresh(transaction)

    return build_transaction_response(transaction)


@router.delete("/{transaction_id}", status_code=204)
def delete_transaction(
    transaction_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> None:
    """Soft delete a transaction."""
    transaction = _load_transaction_or_404(database, transaction_id)

    transaction.deleted_at = datetime.now(UTC)
    database.commit()


@router.put("/{transaction_id}/private", response_model=TransactionResponse)
def mark_private(
    transaction_id: str,
    body: MarkPrivateRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> TransactionResponse:
    """Mark a transaction as private (excluded from DATEV export)."""
    transaction = _load_transaction_or_404(database, transaction_id)

    transaction.is_private = body.is_private
    database.commit()
    database.refresh(transaction)

    return build_transaction_response(transaction)


def _is_duplicate_by_window(
    database: Session,
    transaction_date: date_type,
    amount: Decimal,
    counterparty: str,
    source_config_id: str,
) -> bool:
    """Check if a transaction is a duplicate using window-based detection.

    Duplicate detection: same amount + date + counterparty + source within ±1 day window.
    Used for marketplace imports (Etsy, Amazon, etc.) where no import hash is available.
    """
    existing = database.scalars(
        select(Transaction)
        .where(
            and_(
                Transaction.source_config_id == source_config_id,
                Transaction.date >= transaction_date - timedelta(days=1),
                Transaction.date <= transaction_date + timedelta(days=1),
                Transaction.amount == amount,
                Transaction.counterparty == counterparty,
                Transaction.deleted_at.is_(None),
            )
        )
        .limit(1)
    ).first()

    return existing is not None


def _is_duplicate_by_hash(database: Session, import_hash: str) -> bool:
    """Check if a transaction with this import_hash already exists.

    Hash-based duplicate detection for generic bank imports.
    O(1) lookup via indexed column.
    """
    existing = database.scalars(
        select(Transaction)
        .where(
            and_(
                Transaction.import_hash == import_hash,
                Transaction.deleted_at.is_(None),
            )
        )
        .limit(1)
    ).first()

    return existing is not None


@router.post("/find-matching-receipts")
def find_matching_receipts(
    data: FindMatchingReceiptsRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> FindMatchingReceiptsResponse:
    """Find receipts matching selected transactions (reverse lookup for Sammelbeleg).

    Used from transactions list → "Beleg verknüpfen" → "Bestehenden Beleg suchen".
    Calculates sum of selected transactions, finds unlinked receipts with matching amount.
    """
    from app.models.receipt import Receipt

    # Load selected transactions
    transactions = database.scalars(
        select(Transaction).where(
            Transaction.id.in_(data.transaction_ids),
            Transaction.deleted_at.is_(None),
        )
    ).all()

    found_ids = {tx.id for tx in transactions}
    not_found_ids = set(data.transaction_ids) - found_ids
    if not_found_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Transactions not found: {', '.join(sorted(not_found_ids)[:5])}",
        )

    # Calculate total of selected transactions
    selected_total = sum((abs(tx.amount) for tx in transactions), Decimal("0"))

    # Determine source and date range from selected transactions
    source_config_ids = {tx.source_config_id for tx in transactions if tx.source_config_id}
    dates = [tx.date for tx in transactions]
    date_min = min(dates)
    date_max = max(dates)

    # Find unlinked receipts that could match
    # A receipt is "unlinked" if it has no transaction links
    linked_receipt_ids_subquery = select(ReceiptTransactionLink.receipt_id).distinct()

    candidates_query = (
        select(Receipt)
        .where(
            Receipt.deleted_at.is_(None),
            ~Receipt.id.in_(linked_receipt_ids_subquery),
        )
        .options(joinedload(Receipt.line_items))
    )

    candidates = database.execute(candidates_query).unique().scalars().all()

    # Score each candidate
    matching_receipts = []
    for receipt in candidates:
        receipt_amount = sum((abs(li.amount) for li in receipt.line_items), Decimal("0"))
        if receipt_amount == Decimal("0"):
            continue

        score = Decimal("0")

        # Amount match (strongest signal)
        amount_diff = abs(selected_total - receipt_amount)
        if amount_diff <= Decimal("0.02"):
            score += Decimal("0.6")
        elif amount_diff <= Decimal("1.00"):
            score += Decimal("0.3")
        elif amount_diff <= Decimal("10.00"):
            score += Decimal("0.1")
        else:
            continue  # Skip if amount difference too large

        # Date proximity (receipt date within same month as transactions)
        month_start = date_min.replace(day=1)
        if date_max.month == 12:
            month_end = date_max.replace(year=date_max.year + 1, month=1, day=1)
        else:
            month_end = date_max.replace(month=date_max.month + 1, day=1)

        if month_start <= receipt.date < month_end:
            score += Decimal("0.2")
        elif abs((receipt.date - date_min).days) <= 45:
            score += Decimal("0.1")

        # Source match (receipt counterparty matches transaction source)
        if source_config_ids:
            from app.models.source import TransactionSourceConfig

            sources = database.scalars(
                select(TransactionSourceConfig).where(
                    TransactionSourceConfig.id.in_(source_config_ids),
                )
            ).all()
            source_names = {s.name.lower() for s in sources}
            if receipt.counterparty and receipt.counterparty.lower() in source_names:
                score += Decimal("0.2")
            elif receipt.counterparty and any(name in receipt.counterparty.lower() or receipt.counterparty.lower() in name for name in source_names):
                score += Decimal("0.1")

        matching_receipts.append(
            MatchingReceiptSummary(
                id=receipt.id,
                receipt_number=receipt.receipt_number,
                date=receipt.date,
                counterparty=receipt.counterparty,
                amount=receipt_amount,
                type=receipt.type.value,
                has_file=bool(receipt.file_storage_id),
                match_score=float(score),
            )
        )

    # Sort by score descending
    matching_receipts.sort(key=lambda r: r.match_score, reverse=True)

    return FindMatchingReceiptsResponse(
        matching_receipts=matching_receipts[:20],
        selected_total=selected_total,
        transaction_count=len(transactions),
    )


@router.post("/import", response_model=TransactionImportResponse, status_code=201)
def import_transactions(
    data: TransactionImportRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> TransactionImportResponse:
    """Bulk import transactions from parsed CSV.

    Requires source_config_id (FK to TransactionSourceConfig).

    Duplicate detection:
    - For CSV_MAPPING sources (bank imports): uses hash-based detection
    - For CSV_PARSER sources (marketplace imports): uses window-based detection
    """
    from app.models.source import SourceType, TransactionSourceConfig
    from app.schemas.transaction import TransactionImportError
    from app.services.generic_csv_parser import compute_import_hash

    # Validate source_config_id exists
    source_config = database.scalars(
        select(TransactionSourceConfig).where(
            TransactionSourceConfig.id == data.source_config_id,
        )
    ).first()
    if not source_config:
        raise_not_found("Source config", data.source_config_id)

    imported_count = 0
    skipped_count = 0
    error_count = 0
    errors: list[TransactionImportError] = []
    new_transaction_ids: list[str] = []

    # Use hash-based detection for CSV_MAPPING and MARKETPLACE_MAPPING sources
    use_hash_detection = source_config.type in (SourceType.CSV_MAPPING, SourceType.MARKETPLACE_MAPPING)

    for row_index, item in enumerate(data.items):
        try:
            # Use pre-computed import_hash from marketplace parser if provided,
            # otherwise compute for CSV_MAPPING sources
            import_hash = item.import_hash
            if import_hash is None and use_hash_detection:
                import_hash = compute_import_hash(
                    source_config_id=data.source_config_id,
                    transaction_date=item.date,
                    amount=Decimal(str(item.amount)),
                    counterparty=item.counterparty,
                )

            # Check for duplicates if enabled
            if data.skip_duplicates:
                if use_hash_detection and import_hash:
                    if _is_duplicate_by_hash(database, import_hash):
                        skipped_count += 1
                        continue
                else:
                    if _is_duplicate_by_window(
                        database,
                        item.date,
                        item.amount,
                        item.counterparty,
                        data.source_config_id,
                    ):
                        skipped_count += 1
                        continue

            # oms_order_id is a dedicated column; strip it from extra_data to avoid redundant storage
            if item.extra_data:
                item.extra_data.pop("oms_order_id", None)

            transaction = Transaction(
                id=str(uuid4()),
                user_id=user.id,
                date=item.date,
                amount=item.amount,
                counterparty=item.counterparty,
                description=item.description,
                source_config_id=data.source_config_id,
                source_reference=item.source_reference,
                import_hash=import_hash,
                is_internal_transfer=item.is_internal_transfer,
                extra_data=item.extra_data,
                oms_order_id=item.oms_order_id,
            )
            database.add(transaction)
            new_transaction_ids.append(transaction.id)
            imported_count += 1

        except Exception as exc:
            error_count += 1
            errors.append(TransactionImportError(row_index=row_index, error=str(exc)))

    # Create import log
    import_log = ImportLog(
        id=str(uuid4()),
        user_id=user.id,
        filename=f"{source_config.name}_import_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
        source_config_id=data.source_config_id,
        row_count=len(data.items),
        imported_count=imported_count,
    )
    database.add(import_log)

    database.commit()

    # Audit log for security monitoring
    from app.services.audit import log_bulk_import

    log_bulk_import(
        user_id=user.id,
        source=source_config.name,
        row_count=imported_count,
        success=True,
    )

    # Auto-link imported transactions to receipts (non-fatal: import must not roll back on link failure)
    linked_count = 0
    no_receipt_count = 0
    skipped_locked_count = 0
    if new_transaction_ids:
        try:
            link_result = auto_link_by_oms_order_id(database, user.id, new_transaction_ids)
            database.commit()
            linked_count = link_result.linked
            no_receipt_count = link_result.no_receipt
            skipped_locked_count = link_result.skipped_locked
        except Exception as exc:
            logger.warning(f"Auto-link after import failed (import preserved): {exc}")
            database.rollback()

    return TransactionImportResponse(
        imported_count=imported_count,
        skipped_count=skipped_count,
        error_count=error_count,
        errors=errors,
        import_log_id=import_log.id,
        linked_count=linked_count,
        no_receipt_count=no_receipt_count,
        skipped_locked_count=skipped_locked_count,
    )


@router.post("/auto-link-receipts", response_model=AutoLinkResponse)
def auto_link_receipts(
    payload: AutoLinkRequest,
    date_from: date_type | None = Query(None),
    date_to: date_type | None = Query(None),
    source_config_id: str | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> AutoLinkResponse:
    """Auto-link revenue transactions to receipts by exact oms_order_id match.

    Scope resolution (most specific wins):
    - Explicit transaction_ids in the body, OR
    - date_from / date_to / source_config_id query params (page-filter scope), OR
    - no scope → all matching revenue transactions with an oms_order_id
    """
    transaction_ids = payload.transaction_ids
    if transaction_ids is None and (date_from or date_to or source_config_id):
        scope_query = select(Transaction.id).where(Transaction.deleted_at.is_(None))
        if date_from:
            scope_query = scope_query.where(Transaction.date >= date_from)
        if date_to:
            scope_query = scope_query.where(Transaction.date <= date_to)
        if source_config_id:
            scope_query = scope_query.where(Transaction.source_config_id == source_config_id)
        transaction_ids = list(database.execute(scope_query).scalars().all())

    result = auto_link_by_oms_order_id(database, user.id, transaction_ids)
    database.commit()

    return AutoLinkResponse(
        linked=result.linked,
        already_linked=result.already_linked,
        no_receipt=result.no_receipt,
        skipped_locked=result.skipped_locked,
    )


# --- Internal Transfer (Geldbewegung) Endpoints ---


@router.get("/{transaction_id}/transfer-suggestions", response_model=list[TransferSuggestion])
def get_transfer_suggestions(
    transaction_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> list[TransferSuggestion]:
    """Get suggestions for counter-transactions to link as internal transfer (Geldbewegung).

    Suggests transactions that:
    - Have the same absolute amount (opposite sign)
    - Are from a different source
    - Are within ±5 days
    - Are not already linked as internal transfer
    """
    # Get the source transaction
    transaction = _load_transaction_or_404(database, transaction_id)

    # Search for potential matches
    target_amount = abs(transaction.amount)
    date_start = transaction.date - timedelta(days=5)
    date_end = transaction.date + timedelta(days=5)

    suggestions_query = (
        select(Transaction)
        .where(
            Transaction.deleted_at.is_(None),
            Transaction.id != transaction_id,
            Transaction.source_config_id != transaction.source_config_id,  # Different source
            Transaction.linked_transfer_id.is_(None),  # Not already linked
            Transaction.date >= date_start,
            Transaction.date <= date_end,
        )
        .options(joinedload(Transaction.source_config))
    )

    candidates = database.scalars(suggestions_query).all()

    # Filter by matching absolute amount (±0.01 tolerance for rounding)
    suggestions = []
    for candidate in candidates:
        if abs(abs(candidate.amount) - target_amount) < Decimal("0.01"):
            suggestions.append(
                TransferSuggestion(
                    id=candidate.id,
                    date=candidate.date,
                    amount=candidate.amount,
                    counterparty=candidate.counterparty,
                    source_config_name=candidate.source_config.name if candidate.source_config else None,
                    description=candidate.description,
                )
            )

    return suggestions


@router.post("/{transaction_id}/link-transfer", response_model=TransactionResponse)
def link_transfer(
    transaction_id: str,
    data: TransferLinkRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> TransactionResponse:
    """Link two transactions as internal transfer (Geldbewegung).

    Both transactions will be marked as is_internal_transfer=True
    and linked_transfer_id will point to each other.

    Validates:
    - Both transactions exist and belong to user
    - Different sources
    - Neither is already linked as transfer
    """
    # Get source transaction
    source_query = _build_base_query().where(Transaction.id == transaction_id)
    source_transaction = database.scalars(source_query).first()

    if not source_transaction:
        raise_not_found("Source transaction", transaction_id)

    if source_transaction.linked_transfer_id:
        raise HTTPException(status_code=409, detail="Source transaction is already linked as internal transfer")

    # Get target transaction
    target_query = _build_base_query().where(Transaction.id == data.target_transaction_id)
    target_transaction = database.scalars(target_query).first()

    if not target_transaction:
        raise_not_found("Target transaction", data.target_transaction_id)

    if target_transaction.linked_transfer_id:
        raise HTTPException(status_code=409, detail="Target transaction is already linked as internal transfer")

    # Validate different sources
    if source_transaction.source_config_id == target_transaction.source_config_id:
        raise HTTPException(
            status_code=400,
            detail="Internal transfers must be between different sources (e.g., bank to PayPal)",
        )

    # Link them bidirectionally
    source_transaction.linked_transfer_id = target_transaction.id
    source_transaction.is_internal_transfer = True
    target_transaction.linked_transfer_id = source_transaction.id
    target_transaction.is_internal_transfer = True

    database.commit()

    # Reload with relationships
    return build_transaction_response(_load_transaction_or_404(database, transaction_id))


@router.post("/{transaction_id}/unlink-transfer", response_model=TransactionResponse)
def unlink_transfer(
    transaction_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> TransactionResponse:
    """Remove internal transfer (Geldbewegung) link from both transactions."""
    # Get source transaction
    source_transaction = _load_transaction_or_404(database, transaction_id)

    if not source_transaction.linked_transfer_id:
        raise HTTPException(status_code=400, detail="Transaction is not linked as internal transfer")

    # Get linked transaction
    target_id = source_transaction.linked_transfer_id
    target_query = _build_base_query().where(Transaction.id == target_id)
    target_transaction = database.scalars(target_query).first()

    # Unlink source
    source_transaction.linked_transfer_id = None
    source_transaction.is_internal_transfer = False

    # Unlink target if it exists
    if target_transaction:
        target_transaction.linked_transfer_id = None
        target_transaction.is_internal_transfer = False

    database.commit()

    # Reload with relationships
    return build_transaction_response(_load_transaction_or_404(database, transaction_id))
