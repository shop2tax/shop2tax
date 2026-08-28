"""Receipt-to-payment matching suggestions.

Suggests matches based on:
- Amount match (exact or within tolerance)
- Counterparty similarity (normalized comparison)
- Date proximity (within 7 days)
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.receipt import Receipt
from app.models.receipt_transaction_link import ReceiptTransactionLink
from app.models.transaction import Transaction

# Maximum days between receipt and payment for match suggestion
DATE_TOLERANCE_DAYS = 7

# Maximum amount difference for fuzzy matching (in EUR)
AMOUNT_TOLERANCE = Decimal("0.50")

# German company suffixes to strip for matching (not for storage)
_COMPANY_SUFFIXES = re.compile(
    r"\s*\b(?:gmbh|ug|ag|ohg|kg|gbr|e\.k\.|e\.v\.|mbh|& co\.?)\s*",
    re.IGNORECASE,
)


def _normalize_counterparty(name: str | None) -> str:
    """Normalize counterparty name for matching.

    1. Strip whitespace
    2. Lowercase
    3. Collapse multiple whitespace to single space
    4. Remove German company suffixes
    """
    if not name:
        return ""
    normalized = name.strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = _COMPANY_SUFFIXES.sub(" ", normalized).strip()
    return normalized


@dataclass
class MatchSuggestion:
    """A suggested match between receipt and payment."""

    id: str  # Receipt ID or Transaction ID (depends on direction)
    receipt_number: str | None = None
    receipt_counterparty: str | None = None
    receipt_type: str | None = None  # "revenue" or "expense"
    transaction_counterparty: str | None = None
    source_config_name: str | None = None
    amount: Decimal = Decimal("0")
    date: str = ""  # ISO date string
    confidence: float = 0.0
    reasons: list[str] | None = None

    def __post_init__(self) -> None:
        if self.reasons is None:
            self.reasons = []


def _compute_receipt_amount(receipt: Receipt) -> Decimal:
    """Compute receipt amount from line items (sum)."""
    return sum((li.amount for li in receipt.line_items), Decimal("0.00"))


def _score_amount(receipt_amount: Decimal, transaction_amount: Decimal) -> tuple[float, str | None]:
    """Score amount match. Returns (confidence_delta, reason) or (0, None) for no match."""
    diff = abs(receipt_amount - transaction_amount)
    if diff == Decimal("0"):
        return (0.6, "Exact amount match")
    if diff <= AMOUNT_TOLERANCE:
        return (0.4, f"Amount within tolerance (±{AMOUNT_TOLERANCE}€)")
    return (0.0, None)


def _score_counterparty(receipt_counterparty: str | None, transaction_counterparty: str | None) -> tuple[float, str | None]:
    """Score counterparty match. Returns (confidence_delta, reason) or (0, None) for no match."""
    normalized_receipt = _normalize_counterparty(receipt_counterparty)
    normalized_transaction = _normalize_counterparty(transaction_counterparty)

    if not normalized_receipt or not normalized_transaction:
        return (0.0, None)

    if normalized_receipt == normalized_transaction:
        return (0.2, "Counterparty match")
    if normalized_receipt in normalized_transaction or normalized_transaction in normalized_receipt:
        return (0.1, "Counterparty partial match")
    return (0.0, None)


def _score_date(receipt_date, transaction_date) -> tuple[float, str | None]:
    """Score date proximity. Returns (confidence_delta, reason) or (0, None) if too far apart."""
    date_diff = abs((receipt_date - transaction_date).days)

    if date_diff == 0:
        return (0.4, "Same date")
    if date_diff <= 2:
        return (0.3, f"Date within {date_diff} day(s)")
    if date_diff <= DATE_TOLERANCE_DAYS:
        return (0.1, f"Date within {date_diff} days")
    return (0.0, None)


def suggest_matches_for_receipt(
    database: Session,
    receipt_id: str,
    source_config_id: str | None = None,
    search: str | None = None,
) -> list[MatchSuggestion]:
    """Suggest payments (transactions) that might match a receipt.

    Args:
        db: Database session
        receipt_id: Receipt to find matches for
        source_config_id: Optional filter by bank account
        search: Optional counterparty text search

    Returns:
        List of match suggestions sorted by confidence (descending)
    """
    from sqlalchemy.orm import joinedload

    # Get the receipt with line items
    receipt = (
        database.execute(
            select(Receipt)
            .options(joinedload(Receipt.line_items))
            .where(
                Receipt.id == receipt_id,
                Receipt.deleted_at.is_(None),
            )
        )
        .unique()
        .scalar_one_or_none()
    )

    if receipt is None:
        return []

    # Get transaction IDs that already have linked receipts
    linked_transaction_ids = set(database.execute(select(ReceiptTransactionLink.transaction_id)).scalars().all())

    # Build transaction query with optional filters
    statement = (
        select(Transaction)
        .options(joinedload(Transaction.source_config))
        .where(
            Transaction.deleted_at.is_(None),
            Transaction.is_private.is_(False),
            Transaction.is_internal_transfer.is_(False),
        )
    )

    if source_config_id:
        statement = statement.where(Transaction.source_config_id == source_config_id)

    if search:
        statement = statement.where(Transaction.counterparty.ilike(f"%{search}%"))

    transactions = database.execute(statement).unique().scalars().all()

    suggestions: list[MatchSuggestion] = []
    receipt_date = receipt.date
    receipt_amount = _compute_receipt_amount(receipt)

    for transaction in transactions:
        # Skip transactions that already have receipts linked
        if transaction.id in linked_transaction_ids:
            continue

        reasons: list[str] = []
        confidence = 0.0

        # Amount matching (compare absolute values)
        amount_score, amount_reason = _score_amount(receipt_amount, abs(transaction.amount))
        if amount_reason is None:
            continue  # No amount match at all → skip
        reasons.append(amount_reason)
        confidence += amount_score

        # Counterparty matching
        cp_score, cp_reason = _score_counterparty(receipt.counterparty, transaction.counterparty)
        if cp_reason:
            reasons.append(cp_reason)
            confidence += cp_score

        # Date proximity
        date_score, date_reason = _score_date(receipt_date, transaction.date)
        if date_reason is None:
            continue  # Too far apart → skip
        reasons.append(date_reason)
        confidence += date_score

        suggestions.append(
            MatchSuggestion(
                id=transaction.id,
                transaction_counterparty=transaction.counterparty,
                source_config_name=transaction.source_config.name if transaction.source_config else None,
                amount=transaction.amount,
                date=str(transaction.date),
                confidence=confidence,
                reasons=reasons,
            )
        )

    # Sort by confidence descending, then by date proximity
    suggestions.sort(key=lambda s: (-s.confidence, s.date))

    return suggestions


def suggest_receipts_for_payment(
    database: Session,
    transaction_id: str,
    receipt_type: str | None = None,
    search: str | None = None,
) -> list[MatchSuggestion]:
    """Suggest receipts that might match a payment (transaction).

    Args:
        db: Database session
        transaction_id: Transaction to find matches for
        receipt_type: Optional filter by receipt type (revenue/expense)
        search: Optional counterparty text search

    Returns:
        List of match suggestions sorted by confidence (descending)
    """
    from sqlalchemy.orm import joinedload

    # Get the transaction
    transaction = database.execute(
        select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if transaction is None:
        return []

    # Get receipt IDs that are already linked
    linked_receipt_ids = set(database.execute(select(ReceiptTransactionLink.receipt_id)).scalars().all())

    # Build receipt query with optional filters
    statement = (
        select(Receipt)
        .options(joinedload(Receipt.line_items))
        .where(
            Receipt.deleted_at.is_(None),
        )
    )

    if receipt_type:
        statement = statement.where(Receipt.type == receipt_type)

    if search:
        statement = statement.where(Receipt.counterparty.ilike(f"%{search}%"))

    receipts = database.execute(statement).unique().scalars().all()

    suggestions: list[MatchSuggestion] = []
    transaction_date = transaction.date
    transaction_amount = abs(transaction.amount)

    for receipt in receipts:
        # Skip if receipt already linked
        if receipt.id in linked_receipt_ids:
            continue

        reasons: list[str] = []
        confidence = 0.0

        # Amount matching (computed from line items)
        receipt_amount = _compute_receipt_amount(receipt)
        amount_score, amount_reason = _score_amount(receipt_amount, transaction_amount)
        if amount_reason is None:
            continue
        reasons.append(amount_reason)
        confidence += amount_score

        # Counterparty matching
        cp_score, cp_reason = _score_counterparty(receipt.counterparty, transaction.counterparty)
        if cp_reason:
            reasons.append(cp_reason)
            confidence += cp_score

        # Date proximity
        date_score, date_reason = _score_date(receipt.date, transaction_date)
        if date_reason is None:
            continue
        reasons.append(date_reason)
        confidence += date_score

        suggestions.append(
            MatchSuggestion(
                id=receipt.id,
                receipt_number=receipt.receipt_number,
                receipt_counterparty=receipt.counterparty,
                receipt_type=receipt.type.value,
                amount=receipt_amount,
                date=str(receipt.date),
                confidence=confidence,
                reasons=reasons,
            )
        )

    # Sort by confidence descending, then by date proximity
    suggestions.sort(key=lambda s: (-s.confidence, s.date))

    return suggestions
