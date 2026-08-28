"""Core receipt business logic (GoBD-compliant).

Handles receipt CRUD with audit logging.
All receipt content fields are immutable after finalization (status='final').
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.receipt import Receipt, ReceiptType
from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog
from app.models.receipt_line_item import ReceiptLineItem, TaxRule
from app.models.receipt_transaction_link import ReceiptTransactionLink
from app.models.transaction import Transaction
from app.services.receipt_storage import store_file


@dataclass
class ReceiptLineItemInput:
    """Input for creating a receipt line item.

    Generic input structure, not Billbee-specific. Reusable for PayPal sync etc.
    """

    description: str
    amount: Decimal  # Can be negative (discounts)
    skr03_account_id: int
    tax_rule: TaxRule
    tax_rate: Decimal


# SKR03 account IDs we need (id IS the SKR03 account number)
# These are seeded in app/seed.py:
# - 8195: Erlöse als Kleinunternehmer §19 UStG
# - 8400: Erlöse 19% USt
# - 8300: Erlöse 7% USt
SKR03_KLEINUNTERNEHMER = 8195
SKR03_REVENUE_19 = 8400
SKR03_REVENUE_7 = 8300


def determine_line_item_accounting(
    is_small_business: bool,
    tax_rate_1: Decimal | None,
    tax_rate_2: Decimal | None,
    tax_index: int,
    database: Session,
) -> tuple[int, TaxRule, Decimal]:
    """Determine SKR03 account, tax rule, and tax rate for a line item.

    Returns: (skr03_account_id, tax_rule, tax_rate)

    Kleinunternehmer: always 8195, NO_TAX, 0%
    Regelbesteuert:
      - TaxIndex 1 → TaxRate1 (usually 19%) → SKR03 8400
      - TaxIndex 2 → TaxRate2 (usually 7%) → SKR03 8300
    """
    # Note: SKR03Account.id IS the account number (e.g., 8195, 8400, 8300)
    # We can use the IDs directly without looking them up

    if is_small_business:
        # Kleinunternehmer §19 UStG → 8195, no tax
        return (SKR03_KLEINUNTERNEHMER, TaxRule.NO_TAX, Decimal("0"))

    # Regelbesteuert: determine tax rate and account based on TaxIndex
    if tax_index == 2:
        # Reduced rate (usually 7%)
        tax_rate = tax_rate_2 if tax_rate_2 is not None else Decimal("7")
        return (SKR03_REVENUE_7, TaxRule.TAX_INCLUDED, tax_rate)
    else:
        # Regular rate (usually 19%), TaxIndex=1 or default
        tax_rate = tax_rate_1 if tax_rate_1 is not None else Decimal("19")
        return (SKR03_REVENUE_19, TaxRule.TAX_INCLUDED, tax_rate)


class ReceiptError(Exception):
    """Base exception for receipt operations."""


class ReceiptNotFoundError(ReceiptError):
    """Receipt not found or not owned by user."""


class ReceiptAlreadyLinkedError(ReceiptError):
    """Receipt is already linked to a payment."""


class ReceiptLockedError(ReceiptError):
    """Receipt is locked (fiscal year finalized)."""


def require_unlocked(receipt: Receipt) -> None:
    """Raise ReceiptLockedError if receipt is locked (GoBD immutability)."""
    if receipt.is_locked:
        raise ReceiptLockedError(f"Receipt {receipt.id} is locked (GoBD immutability)")


class DuplicateOmsReceiptError(ReceiptError):
    """Receipt with this OMS order ID already exists."""


def _create_audit_log(
    database: Session,
    receipt_id: str,
    user_id: str,
    action: ReceiptAuditAction,
    details: dict | None = None,
) -> ReceiptAuditLog:
    """Create an audit log entry for a receipt operation."""
    log = ReceiptAuditLog(
        receipt_id=receipt_id,
        user_id=user_id,
        action=action,
        details=details,
    )
    database.add(log)
    return log


def _get_receipt(database: Session, receipt_id: str) -> Receipt:
    """Get receipt by ID, ensuring it is not deleted."""
    statement = select(Receipt).where(
        Receipt.id == receipt_id,
        Receipt.deleted_at.is_(None),
    )
    receipt = database.execute(statement).scalar_one_or_none()
    if receipt is None:
        raise ReceiptNotFoundError(f"Receipt {receipt_id} not found")
    return receipt


def _update_payment_status(database: Session, receipt: Receipt) -> None:
    """Update receipt payment_status based on active links and open_amount.

    Called within the same DB transaction as link/unlink operations.
    Supports M:N relationship (Sammelbeleg → N Transactions).

    Status logic:
    - 'unpaid': No active links
    - 'partial': Has links but open_amount > 0 (Sammelbeleg not complete)
    - 'paid': open_amount ≈ 0 (fully covered by linked transactions)
    """
    from sqlalchemy import func

    # Get sum of linked transaction amounts (only non-deleted)
    result = database.execute(
        select(
            func.count(ReceiptTransactionLink.id).label("link_count"),
            func.coalesce(func.sum(func.abs(Transaction.amount)), 0).label("linked_total"),
        )
        .join(Transaction, Transaction.id == ReceiptTransactionLink.transaction_id)
        .where(
            ReceiptTransactionLink.receipt_id == receipt.id,
            Transaction.deleted_at.is_(None),
        )
    ).one()

    link_count = result.link_count
    linked_total = Decimal(str(result.linked_total))

    if link_count == 0:
        receipt.payment_status = "unpaid"
        return

    # Calculate receipt total from line items (SQL query — doesn't require loaded relationship)
    receipt_total_result = database.execute(
        select(func.coalesce(func.sum(func.abs(ReceiptLineItem.amount)), 0)).where(
            ReceiptLineItem.receipt_id == receipt.id,
        )
    ).scalar_one()
    receipt_total = Decimal(str(receipt_total_result))
    open_amount = receipt_total - linked_total

    if open_amount <= Decimal("0.02"):
        receipt.payment_status = "paid"
    else:
        receipt.payment_status = "partial"


@dataclass
class StoredFileMetadata:
    """Pre-stored file metadata (from run_in_threadpool(store_file, ...))."""

    file_hash: str
    file_storage_id: str
    file_mime_type: str
    file_original_name: str


def create_revenue_receipt(
    database: Session,
    user_id: str,
    oms_order_id: str,
    receipt_number: str,
    receipt_date: date,
    counterparty: str,
    description: str,
    line_items: list[ReceiptLineItemInput],
    file_metadata: StoredFileMetadata | None = None,
    oms_provider_id: str | None = None,
    oms_invoice_number: str | None = None,
    oms_shop_name: str | None = None,
    oms_platform: str | None = None,
    payment_date: date | None = None,
    source: str = "billbee",
) -> Receipt:
    """Create a revenue receipt with line items and optional PDF.

    Args:
        database: Database session
        user_id: Owner's user ID
        oms_order_id: OMS order ID (for dedup)
        receipt_number: Invoice/receipt number
        receipt_date: Date of the receipt
        counterparty: Customer name
        description: Receipt description
        line_items: Structured line items with SKR03 assignment
        file_metadata: Pre-stored file metadata (caller stores via run_in_threadpool)
        oms_provider_id: OMS provider record ID this receipt originates from
        oms_invoice_number: OMS invoice number
        oms_shop_name: Shop name in the OMS
        oms_platform: Platform (Etsy, Amazon, etc.)
        source: Audit source identity (provider type value, e.g. "billbee")

    Returns:
        Created Receipt

    Raises:
        DuplicateOmsReceiptError: If receipt with this OMS order ID already exists
    """
    # Check for existing receipt with same OMS order ID (partial unique index is safety net)
    existing = database.execute(
        select(Receipt).where(
            Receipt.oms_order_id == oms_order_id,
            Receipt.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if existing:
        raise DuplicateOmsReceiptError(f"Receipt for OMS order {oms_order_id} already exists")

    # Get RC tax rate from SiteSettings for GoBD historical preservation
    from app.core.constants import DEFAULT_RC_TAX_RATE
    from app.models.site_settings import SiteSettings

    settings = database.execute(select(SiteSettings).where(SiteSettings.id == 1)).scalar_one_or_none()
    rc_tax_rate = settings.rc_tax_rate if settings else DEFAULT_RC_TAX_RATE

    receipt = Receipt(
        user_id=user_id,
        type=ReceiptType.REVENUE,
        receipt_number=receipt_number,
        date=receipt_date,
        counterparty=counterparty,
        description=description,
        oms_provider_id=oms_provider_id,
        oms_order_id=oms_order_id,
        oms_invoice_number=oms_invoice_number,
        oms_shop_name=oms_shop_name,
        oms_platform=oms_platform,
        payment_date=payment_date,
        file_hash=file_metadata.file_hash if file_metadata else None,
        file_storage_id=file_metadata.file_storage_id if file_metadata else None,
        file_original_name=file_metadata.file_original_name if file_metadata else None,
        file_mime_type=file_metadata.file_mime_type if file_metadata else None,
    )
    database.add(receipt)
    database.flush()  # Get ID for line items + audit log

    # Create ReceiptLineItem for each input
    for position, item in enumerate(line_items):
        db_line_item = ReceiptLineItem(
            receipt_id=receipt.id,
            position=position,
            description=item.description,
            amount=item.amount,  # Can be negative (discounts)
            skr03_account_id=item.skr03_account_id,
            tax_rule=item.tax_rule,
            tax_rate=item.tax_rate,
            # Persist RC rate for GoBD compliance (historical rate preserved)
            rc_tax_rate=rc_tax_rate if item.tax_rule.is_reverse_charge() else None,
        )
        database.add(db_line_item)

    details = {"source": source, "oms_order_id": oms_order_id}
    if file_metadata:
        details["file_hash"] = file_metadata.file_hash

    _create_audit_log(database, receipt.id, user_id, ReceiptAuditAction.CREATED, details)

    # GoBD: Create FILE_UPLOADED audit log entry when PDF stored
    if file_metadata:
        _create_audit_log(
            database,
            receipt.id,
            user_id,
            ReceiptAuditAction.FILE_UPLOADED,
            {"object_name": file_metadata.file_storage_id, "file_hash": file_metadata.file_hash},
        )

    return receipt


def create_expense_receipt(
    database: Session,
    user_id: str,
    receipt_number: str,
    receipt_date: date,
    amount: Decimal,
    counterparty: str,
    description: str = "",
    skr03_account_id: int | None = None,
    file_content: bytes | None = None,
    file_original_name: str | None = None,
) -> Receipt:
    """Create an expense receipt with optional file attachment.

    Args:
        db: Database session
        user_id: Owner's user ID
        receipt_number: Invoice/receipt number
        receipt_date: Date of the receipt
        amount: Total amount (positive)
        counterparty: Supplier/vendor name
        description: Optional description
        skr03_account_id: Optional SKR03 account assignment
        file_content: Optional file bytes
        file_original_name: Original filename (required if file_content provided)

    Returns:
        Created Receipt

    Raises:
        FileStorageError: If file storage fails
    """
    # Store file if provided
    file_hash = None
    file_storage_id = None
    file_mime_type = None

    if file_content and file_original_name:
        file_hash, file_storage_id, file_mime_type = store_file(file_content, file_original_name)

    receipt = Receipt(
        user_id=user_id,
        type=ReceiptType.EXPENSE,
        receipt_number=receipt_number,
        date=receipt_date,
        counterparty=counterparty,
        description=description,
        file_hash=file_hash,
        file_storage_id=file_storage_id,
        file_original_name=file_original_name,
        file_mime_type=file_mime_type,
    )
    database.add(receipt)
    database.flush()  # Get ID for line items + audit log

    # Amount + SKR03 live on ReceiptLineItem, not on Receipt
    line_item = ReceiptLineItem(
        receipt_id=receipt.id,
        position=0,
        description=description,
        amount=abs(amount),
        skr03_account_id=skr03_account_id,
    )
    database.add(line_item)

    details = {"source": "manual"}
    if file_hash:
        details["file_hash"] = file_hash

    _create_audit_log(database, receipt.id, user_id, ReceiptAuditAction.CREATED, details)

    if file_storage_id:
        _create_audit_log(
            database,
            receipt.id,
            user_id,
            ReceiptAuditAction.FILE_UPLOADED,
            {"object_name": file_storage_id, "file_hash": file_hash},
        )

    return receipt


def link_receipt_to_payment(
    database: Session,
    receipt_id: str,
    transaction_id: str,
    user_id: str,
) -> tuple[Receipt, Transaction]:
    """Link a receipt to a payment (transaction) via junction table.

    Supports M:N (Sammelbeleg). Idempotent for same receipt+transaction pair.

    Args:
        db: Database session
        receipt_id: Receipt to link
        transaction_id: Transaction (payment) to link
        user_id: User performing the operation

    Returns:
        Tuple of (Receipt, Transaction) after linking

    Raises:
        ReceiptNotFoundError: If receipt or transaction not found
        ReceiptLockedError: If receipt is locked
    """
    receipt = _get_receipt(database, receipt_id)
    require_unlocked(receipt)

    # Check if this specific link already exists (idempotent for same pair)
    existing_link = database.execute(
        select(ReceiptTransactionLink).where(
            ReceiptTransactionLink.receipt_id == receipt_id,
            ReceiptTransactionLink.transaction_id == transaction_id,
        )
    ).scalar_one_or_none()

    if existing_link:
        # Already linked to the same transaction — idempotent
        transaction = database.execute(select(Transaction).where(Transaction.id == transaction_id)).scalar_one()
        return (receipt, transaction)

    # Get transaction
    transaction = database.execute(
        select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if transaction is None:
        raise ReceiptNotFoundError(f"Transaction {transaction_id} not found")

    # Create link in junction table
    link = ReceiptTransactionLink(
        receipt_id=receipt_id,
        transaction_id=transaction_id,
    )
    database.add(link)
    database.flush()

    _update_payment_status(database, receipt)

    _create_audit_log(
        database,
        receipt_id,
        user_id,
        ReceiptAuditAction.LINKED,
        {"transaction_id": transaction_id},
    )

    return (receipt, transaction)


@dataclass
class AutoLinkResult:
    """Outcome of auto-linking transactions to receipts by oms_order_id."""

    linked: int
    already_linked: int
    no_receipt: int
    skipped_locked: int


def auto_link_by_oms_order_id(
    database: Session,
    user_id: str,
    transaction_ids: list[str] | None = None,
) -> AutoLinkResult:
    """Auto-link revenue transactions to receipts via exact oms_order_id match.

    Only revenue transactions (extra_data->>'marketplace_category' == 'revenue') that
    carry an oms_order_id are considered. Each is linked to the receipt sharing the
    same oms_order_id. Locked receipts are skipped (GoBD immutability), not failed.

    Args:
        database: Database session
        user_id: User performing the operation (audit metadata)
        transaction_ids: Optional scope — only these transactions; None means all matching

    Returns:
        AutoLinkResult with per-outcome counts
    """
    result = AutoLinkResult(linked=0, already_linked=0, no_receipt=0, skipped_locked=0)

    query = select(Transaction).where(
        Transaction.oms_order_id.isnot(None),
        Transaction.deleted_at.is_(None),
        Transaction.extra_data["marketplace_category"].astext == "revenue",
    )
    if transaction_ids is not None:
        query = query.where(Transaction.id.in_(transaction_ids))

    transactions = database.execute(query).scalars().all()

    for transaction in transactions:
        receipt = database.execute(
            select(Receipt).where(
                Receipt.oms_order_id == transaction.oms_order_id,
                Receipt.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

        if receipt is None:
            result.no_receipt += 1
            continue

        existing_link = database.execute(
            select(ReceiptTransactionLink.id).where(
                ReceiptTransactionLink.receipt_id == receipt.id,
                ReceiptTransactionLink.transaction_id == transaction.id,
            )
        ).scalar_one_or_none()

        if existing_link is not None:
            result.already_linked += 1
            continue

        try:
            link_receipt_to_payment(database, receipt.id, transaction.id, user_id)
            result.linked += 1
        except ReceiptLockedError:
            result.skipped_locked += 1

    return result


def unlink_receipt_from_payment(
    database: Session,
    receipt_id: str,
    user_id: str,
    transaction_id: str | None = None,
) -> Receipt:
    """Unlink a receipt from a specific transaction via junction table.

    Args:
        db: Database session
        receipt_id: Receipt to unlink
        user_id: User performing the operation
        transaction_id: Specific transaction to unlink. If None, removes ALL links.

    Returns:
        Receipt after unlinking

    Raises:
        ReceiptNotFoundError: If receipt not found or specific link not found
        ReceiptLockedError: If receipt is locked
    """
    receipt = _get_receipt(database, receipt_id)
    require_unlocked(receipt)

    if transaction_id:
        # Unlink specific transaction
        link = database.execute(
            select(ReceiptTransactionLink).where(
                ReceiptTransactionLink.receipt_id == receipt_id,
                ReceiptTransactionLink.transaction_id == transaction_id,
            )
        ).scalar_one_or_none()

        if link is None:
            raise ReceiptNotFoundError(f"No link between receipt {receipt_id} and transaction {transaction_id}")

        database.delete(link)
        database.flush()

        _update_payment_status(database, receipt)

        _create_audit_log(
            database,
            receipt_id,
            user_id,
            ReceiptAuditAction.UNLINKED,
            {"transaction_id": transaction_id},
        )
    else:
        # Unlink ALL transactions (backwards-compatible)
        links = (
            database.execute(
                select(ReceiptTransactionLink).where(
                    ReceiptTransactionLink.receipt_id == receipt_id,
                )
            )
            .scalars()
            .all()
        )

        for link in links:
            _create_audit_log(
                database,
                receipt_id,
                user_id,
                ReceiptAuditAction.UNLINKED,
                {"transaction_id": link.transaction_id},
            )
            database.delete(link)

        if links:
            database.flush()
            _update_payment_status(database, receipt)

    return receipt


def lock_receipts(
    database: Session,
    user_id: str,
    start_date: date,
    end_date: date,
) -> int:
    """Lock all receipts in a date range (fiscal year finalization).

    Args:
        db: Database session
        user_id: User performing the operation (for audit log)
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)

    Returns:
        Number of receipts locked
    """
    # Find unlocked receipts in range (locked_at IS NULL = not locked)
    statement = select(Receipt).where(
        Receipt.date >= start_date,
        Receipt.date <= end_date,
        Receipt.locked_at.is_(None),
        Receipt.deleted_at.is_(None),
    )
    receipts = database.execute(statement).scalars().all()

    locked_count = 0
    now = datetime.now(UTC)

    for receipt in receipts:
        receipt.locked_at = now

        _create_audit_log(
            database,
            receipt.id,
            user_id,
            ReceiptAuditAction.LOCKED,
            {"date_range": f"{start_date} to {end_date}"},
        )
        locked_count += 1

    return locked_count


def record_payment(
    database: Session,
    receipt_id: str,
    user_id: str,
    source_config_id: str,
    payment_date: date,
    amount: Decimal | None = None,
    counterparty: str | None = None,
    description: str | None = None,
) -> tuple[Receipt, Transaction]:
    """Record a manual payment for a receipt.

    Creates a real Transaction and links it to the receipt atomically.

    Args:
        db: Database session
        receipt_id: Receipt to record payment for
        user_id: User performing the operation
        source_config_id: Bank account for the payment
        payment_date: Date of payment
        amount: Payment amount (positive, defaults to receipt total)
        counterparty: Counterparty (defaults to receipt counterparty)
        description: Description (defaults to "Zahlung Beleg #{receipt_number}")

    Returns:
        Tuple of (Receipt, Transaction)

    Raises:
        ReceiptNotFoundError: If receipt not found
        ReceiptLockedError: If receipt is locked
        ValueError: If source_config_id is invalid or amount <= 0
    """
    from uuid import uuid4

    from sqlalchemy.orm import joinedload

    from app.models.source import TransactionSourceConfig

    # Load receipt with line items
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
        raise ReceiptNotFoundError(f"Receipt {receipt_id} not found")
    require_unlocked(receipt)

    # Validate source_config_id
    source_config = database.execute(
        select(TransactionSourceConfig).where(
            TransactionSourceConfig.id == source_config_id,
        )
    ).scalar_one_or_none()
    if source_config is None:
        msg = f"Source config {source_config_id} not found"
        raise ValueError(msg)

    # Compute defaults from receipt
    receipt_amount = sum((li.amount for li in receipt.line_items), Decimal("0.00"))
    payment_amount = amount if amount is not None else receipt_amount
    if payment_amount <= 0:
        msg = "Payment amount must be positive"
        raise ValueError(msg)

    payment_counterparty = counterparty if counterparty is not None else receipt.counterparty
    payment_description = description if description is not None else f"Zahlung Beleg #{receipt.receipt_number}"

    # Apply sign convention: expense → negative, revenue → positive
    signed_amount = -payment_amount if receipt.type == ReceiptType.EXPENSE else payment_amount

    # Create transaction
    transaction = Transaction(
        id=str(uuid4()),
        user_id=user_id,
        date=payment_date,
        amount=signed_amount,
        counterparty=payment_counterparty,
        description=payment_description,
        source_config_id=source_config_id,
    )
    database.add(transaction)
    database.flush()

    # Create link
    link = ReceiptTransactionLink(
        receipt_id=receipt_id,
        transaction_id=transaction.id,
    )
    database.add(link)
    database.flush()

    # Update payment status atomically
    _update_payment_status(database, receipt)

    # Audit log
    _create_audit_log(
        database,
        receipt_id,
        user_id,
        ReceiptAuditAction.PAYMENT_RECORDED,
        {
            "transaction_id": transaction.id,
            "amount": str(signed_amount),
            "source_config_id": source_config_id,
        },
    )

    return (receipt, transaction)
