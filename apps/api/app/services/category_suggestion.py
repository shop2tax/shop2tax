"""Category suggestion service — receipt-native pattern learning.

Learns SKR03 account assignments from finalized receipts and suggests
accounts for new receipts based on counterparty matching.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.sql import escape_like
from app.models.accounting_pattern import AccountingPattern
from app.models.receipt import Receipt


def suggest_for_counterparty(
    database: Session,
    counterparty: str,
) -> int | None:
    """Find best matching SKR03 account ID for a counterparty.

    Matches counterparty against learned patterns using case-insensitive
    containment. Returns the SKR03 account ID with the highest confidence,
    breaking ties by hit count.

    Returns None if no pattern matches.
    """
    statement = (
        select(AccountingPattern)
        .where(
            AccountingPattern.pattern.ilike(f"%{escape_like(counterparty)}%"),
        )
        .order_by(
            AccountingPattern.confidence.desc(),
            AccountingPattern.hits.desc(),
        )
        .limit(1)
    )
    pattern = database.scalars(statement).first()
    if pattern is None:
        return None
    return pattern.skr03_account_id


def learn_from_receipt(database: Session, receipt: Receipt) -> None:
    """Learn accounting patterns from a finalized receipt.

    For each line item with an SKR03 account, upserts an AccountingPattern
    keyed on (counterparty, skr03_account_id) — shared tenant, patterns are global:
    - Existing pattern: increment hits, increase confidence (capped at 1.0)
    - New pattern: create with confidence=0.5, hits=1
    - Account change: reset confidence to 0.5, reset hits to 1
    """
    if not receipt.counterparty:
        return

    counterparty = receipt.counterparty.strip()
    if not counterparty:
        return

    for line_item in receipt.line_items:
        if line_item.skr03_account_id is None:
            continue

        # Find existing pattern for this counterparty (shared tenant: global patterns)
        existing = database.scalars(
            select(AccountingPattern).where(
                AccountingPattern.pattern == counterparty,
            )
        ).first()

        if existing is None:
            # New pattern
            pattern = AccountingPattern(
                user_id=receipt.user_id,  # audit: who created the pattern
                pattern=counterparty,
                skr03_account_id=line_item.skr03_account_id,
                confidence=0.5,
                hits=1,
            )
            database.add(pattern)
        elif existing.skr03_account_id == line_item.skr03_account_id:
            # Same account — reinforce pattern
            existing.hits += 1
            existing.confidence = min(1.0, existing.confidence + 0.1)
        else:
            # Account changed — reset to new account
            existing.skr03_account_id = line_item.skr03_account_id
            existing.confidence = 0.5
            existing.hits = 1

        # Only learn from the first line item with an SKR03 account
        # (one pattern per counterparty, not per line item)
        break
