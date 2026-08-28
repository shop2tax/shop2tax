"""Receipt management router (Beleg-System)."""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.constants import GERMAN_MONTHS
from app.core.exceptions import raise_not_found
from app.core.pagination import PaginationParams, paginate_query
from app.core.rate_limit import get_extraction_rate_limit, global_rate_limit_key, limiter
from app.core.sql import escape_like
from app.database import get_db
from app.deps import CurrentUser, get_current_user
from app.models.receipt import Receipt, ReceiptStatus, ReceiptType
from app.models.receipt_line_item import ReceiptLineItem
from app.models.receipt_transaction_link import ReceiptTransactionLink
from app.models.tag import Tag
from app.models.transaction import Transaction
from app.schemas.extraction import ExtractionResult
from app.schemas.receipt import (
    AccountSuggestionResponse,
    BulkLinkRequest,
    BulkLinkResponse,
    BulkSuggestionResponse,
    BulkUnlinkRequest,
    BulkUnlinkResponse,
    RCComplianceSummary,
    ReceiptCreate,
    ReceiptCreateAndLink,
    ReceiptCreateAndLinkBulk,
    ReceiptLineItemCreate,
    ReceiptLinkRequest,
    ReceiptListResponse,
    ReceiptLockRequest,
    ReceiptMatchSuggestion,
    ReceiptResponse,
    ReceiptUnlinkRequest,
    ReceiptUpdate,
    RecordPaymentRequest,
    TagResponse,
)
from app.services.document_extraction import extract_from_document
from app.services.receipt_matching import suggest_matches_for_receipt
from app.services.receipt_service import (
    ReceiptLockedError,
    ReceiptNotFoundError,
    _update_payment_status,
    link_receipt_to_payment,
    lock_receipts,
    require_unlocked,
    unlink_receipt_from_payment,
)
from app.services.receipt_storage import (
    FileIntegrityError,
    FileValidationError,
    get_file_content,
    store_file,
)
from app.services.response_builders import build_bulk_link_response, build_receipt_response

router = APIRouter(prefix="/api/v1/receipts", tags=["receipts"])


def _build_content_disposition(filename: str | None) -> str:
    """Build a safe Content-Disposition header value.

    Sanitizes the filename to prevent header injection and uses
    RFC 5987 filename* parameter for proper Unicode support.
    """
    import re
    from urllib.parse import quote

    name = filename or "receipt"
    # Strip path separators and control characters
    name = re.sub(r'[/\\"\r\n\x00-\x1f]', "_", name)
    # ASCII-safe fallback: replace non-ASCII with underscore
    ascii_name = name.encode("ascii", "replace").decode("ascii")
    # RFC 5987 UTF-8 encoded version for Unicode filenames
    utf8_name = quote(name, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


def _load_receipt_with_relationships(
    database: Session,
    receipt_id: str,
    require_not_deleted: bool = True,
    relationships: list[str] | None = None,
) -> Receipt:
    """Load a receipt with relationships via joinedload + .unique() pattern.

    Raises a 404 if no matching receipt exists, so callers always get a Receipt.

    Args:
        relationships: Which relationships to eager-load. None = all (default).
            Valid values: "line_items", "transaction_link", "tags".
    """
    conditions = [Receipt.id == receipt_id]
    if require_not_deleted:
        conditions.append(Receipt.deleted_at.is_(None))

    # Build eager-load options based on requested relationships
    load_all = relationships is None
    options = []
    if load_all or "transaction_link" in relationships:
        options.append(joinedload(Receipt.transaction_links).joinedload(ReceiptTransactionLink.transaction))
    if load_all or "line_items" in relationships:
        options.append(joinedload(Receipt.line_items).joinedload(ReceiptLineItem.skr03_account))
    if load_all or "tags" in relationships:
        options.append(joinedload(Receipt.tags))

    receipt = database.execute(select(Receipt).options(*options).where(*conditions)).unique().scalar_one_or_none()
    if receipt is None:
        raise_not_found("Receipt", receipt_id)
    return receipt


def _create_receipt_from_data(
    database: Session,
    data: ReceiptCreate,
    user_id: str,
) -> Receipt:
    """Shared receipt creation logic: instantiate receipt, add line items, write audit log.

    Used by both create_receipt and create_and_link_receipt.
    Returns the flushed receipt (ID available).
    """
    from uuid import uuid4

    from app.core.constants import DEFAULT_RC_TAX_RATE
    from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog
    from app.models.site_settings import SiteSettings

    # Get RC tax rate from SiteSettings for GoBD historical preservation
    settings = database.execute(select(SiteSettings).where(SiteSettings.id == 1)).scalar_one_or_none()
    rc_tax_rate = settings.rc_tax_rate if settings else DEFAULT_RC_TAX_RATE

    receipt = Receipt(
        id=str(uuid4()),
        user_id=user_id,
        type=data.type,
        receipt_number=data.receipt_number,
        date=data.date,
        counterparty=data.counterparty,
        description=data.description,
        status=data.status,
        due_date=data.due_date,
        payment_date=data.payment_date,
        delivery_date=data.delivery_date,
        delivery_period=data.delivery_period,
        currency=data.currency,
        extraction_source=data.extraction_source,
    )
    database.add(receipt)
    database.flush()  # Get ID for line items

    # Create line items (required, validated by schema)
    line_items = _create_line_items_from_request(receipt, data.line_items, rc_tax_rate)
    for li in line_items:
        database.add(li)

    # Audit log
    database.add(
        ReceiptAuditLog(
            receipt_id=receipt.id,
            user_id=user_id,
            action=ReceiptAuditAction.CREATED,
            details={"source": "api", "status": data.status.value},
        )
    )

    return receipt


def _create_line_items_from_request(
    receipt: Receipt,
    line_items_data: list[ReceiptLineItemCreate],
    rc_tax_rate: Decimal | None = None,
) -> list[ReceiptLineItem]:
    """Create ReceiptLineItem instances from request data.

    Args:
        receipt: Parent receipt.
        line_items_data: Line item data from request.
        rc_tax_rate: RC tax rate from SiteSettings. Set on RC items for GoBD historical preservation.
    """
    line_items = []
    for position, item in enumerate(line_items_data):
        line_item = ReceiptLineItem(
            receipt_id=receipt.id,
            position=position,
            description=item.description,
            amount=abs(item.amount),
            skr03_account_id=item.skr03_account_id,
            tax_rule=item.tax_rule,
            tax_rate=item.tax_rate,
            depreciation=item.depreciation,
            # Persist RC rate for GoBD compliance (historical rate preserved)
            rc_tax_rate=rc_tax_rate if item.tax_rule.is_reverse_charge() else None,
        )
        line_items.append(line_item)
    return line_items


# --- Suggestion Endpoint ---


@router.get("/suggest-account", response_model=AccountSuggestionResponse)
def suggest_account(
    counterparty: str = Query(..., min_length=1, description="Counterparty name to match"),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> AccountSuggestionResponse:
    """Suggest SKR03 account based on learned patterns for a counterparty."""
    from app.models.accounting_pattern import AccountingPattern
    from app.services.category_suggestion import suggest_for_counterparty
    from app.services.response_builders import build_account_suggestion_response

    account_id = suggest_for_counterparty(database, counterparty)

    if account_id is None:
        raise_not_found("Suggestion")

    # Load the full pattern for the response (confidence, pattern text)
    pattern = database.scalars(
        select(AccountingPattern)
        .where(
            AccountingPattern.skr03_account_id == account_id,
            AccountingPattern.pattern.ilike(f"%{escape_like(counterparty)}%"),
        )
        .limit(1)
    ).first()

    if pattern is None:
        raise_not_found("Suggestion")

    return build_account_suggestion_response(pattern)


# --- Extraction Endpoint ---

# Allowed MIME types for extraction (PDF, images, XML for XRechnung)
_EXTRACTION_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/xml",
    "text/xml",
}

# 10 MB max file size
_EXTRACTION_MAX_FILE_SIZE = 10 * 1024 * 1024


@router.post("/extract", response_model=ExtractionResult)
@limiter.limit(get_extraction_rate_limit, key_func=global_rate_limit_key)
async def extract_document_data(
    request: Request,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> ExtractionResult:
    """Extract invoice data from uploaded file.

    Accepts: PDF, JPEG, PNG, XML (XRechnung)
    Returns: ExtractionResult with pre-filled fields
    """
    # Validate MIME type
    if file.content_type not in _EXTRACTION_ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Allowed: PDF, JPEG, PNG, XML",
        )

    # Read and validate file size
    file_bytes = await file.read()
    if len(file_bytes) > _EXTRACTION_MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {len(file_bytes)} bytes. Maximum: {_EXTRACTION_MAX_FILE_SIZE} bytes (10 MB)",
        )

    return await extract_from_document(file_bytes, file.content_type, user.id, database)


# --- CRUD Endpoints ---


@router.get("", response_model=ReceiptListResponse)
def list_receipts(
    pagination: PaginationParams = Depends(),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
    tab: Literal["all", "draft", "open", "overdue", "finalized"] | None = Query(None, description="Tab filter: all, draft, open, overdue, finalized"),
    search: str | None = Query(None, description="Text search over receipt_number, counterparty, description"),
    receipt_type: ReceiptType | None = Query(None, description="Filter by type"),
    status: ReceiptStatus | None = Query(None, description="Filter by status (draft/final)"),
    start_date: date | None = Query(None, description="Filter by start date"),
    end_date: date | None = Query(None, description="Filter by end date"),
    is_linked: bool | None = Query(None, description="Filter by link status"),
    is_locked: bool | None = Query(None, description="Filter by lock status"),
    payment_status: str | None = Query(None, description="Filter by payment status (unpaid/paid)"),
) -> ReceiptListResponse:
    """List receipts with optional filters."""
    query = (
        select(Receipt)
        .options(
            joinedload(Receipt.transaction_links).joinedload(ReceiptTransactionLink.transaction),
            joinedload(Receipt.line_items).joinedload(ReceiptLineItem.skr03_account),
            joinedload(Receipt.tags),
        )
        .where(
            Receipt.deleted_at.is_(None),
        )
    )

    # Tab filtering (server-side)
    if tab is not None and tab != "all":
        linked_subquery = select(ReceiptTransactionLink.receipt_id).where(ReceiptTransactionLink.receipt_id == Receipt.id).exists()
        if tab == "draft":
            query = query.where(Receipt.status == ReceiptStatus.DRAFT)
        elif tab == "open":
            query = query.where(~linked_subquery)
        elif tab == "overdue":
            query = query.where(
                Receipt.due_date < date.today(),
                ~linked_subquery,
            )
        elif tab == "finalized":
            query = query.where(Receipt.locked_at.is_not(None))

    # Text search (ILIKE over receipt_number, counterparty, description)
    if search:
        search_pattern = f"%{escape_like(search)}%"
        query = query.where(
            Receipt.receipt_number.ilike(search_pattern) | Receipt.counterparty.ilike(search_pattern) | Receipt.description.ilike(search_pattern)
        )

    if receipt_type is not None:
        query = query.where(Receipt.type == receipt_type)
    if status is not None:
        query = query.where(Receipt.status == status)
    if start_date is not None:
        query = query.where(Receipt.date >= start_date)
    if end_date is not None:
        query = query.where(Receipt.date <= end_date)
    if is_locked is not None:
        if is_locked:
            query = query.where(Receipt.locked_at.is_not(None))
        else:
            query = query.where(Receipt.locked_at.is_(None))
    if is_linked is not None:
        linked_subquery_filter = select(ReceiptTransactionLink.receipt_id).where(ReceiptTransactionLink.receipt_id == Receipt.id).exists()
        if is_linked:
            query = query.where(linked_subquery_filter)
        else:
            query = query.where(~linked_subquery_filter)
    if payment_status is not None:
        query = query.where(Receipt.payment_status == payment_status)

    # Deterministic ordering
    query = query.order_by(Receipt.date.desc(), Receipt.id.desc())

    receipts, total = paginate_query(database, query, pagination)

    return ReceiptListResponse(
        receipts=[build_receipt_response(r) for r in receipts],
        total=total,
    )


@router.post("", response_model=ReceiptResponse, status_code=201)
def create_receipt(
    data: ReceiptCreate,
    database: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> ReceiptResponse:
    """Create a receipt with line items.

    File upload is handled separately via POST /{id}/upload.
    """
    receipt = _create_receipt_from_data(database, data, user.id)
    database.commit()

    receipt = _load_receipt_with_relationships(database, receipt.id)
    return build_receipt_response(receipt)


@router.post("/create-and-link", response_model=ReceiptResponse, status_code=201)
def create_and_link_receipt(
    data: ReceiptCreateAndLink,
    database: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> ReceiptResponse:
    """Create a receipt and link it to a transaction in one request.

    Used from transaction → create receipt flow.
    File upload is handled separately via POST /{id}/upload.
    """
    from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog

    # Verify transaction exists
    transaction = database.execute(
        select(Transaction).where(
            Transaction.id == data.transaction_id,
            Transaction.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if transaction is None:
        raise_not_found("Transaction", data.transaction_id)

    # Create receipt (shared logic)
    receipt = _create_receipt_from_data(database, data, user.id)

    # Create link
    link = ReceiptTransactionLink(
        receipt_id=receipt.id,
        transaction_id=data.transaction_id,
    )
    database.add(link)
    database.flush()

    # Update payment status atomically
    _update_payment_status(database, receipt)

    # Link audit log
    database.add(
        ReceiptAuditLog(
            receipt_id=receipt.id,
            user_id=user.id,
            action=ReceiptAuditAction.LINKED,
            details={"transaction_id": data.transaction_id},
        )
    )

    database.commit()

    receipt = _load_receipt_with_relationships(database, receipt.id)
    return build_receipt_response(receipt)


@router.post("/create-and-link-bulk", response_model=ReceiptResponse, status_code=201)
def create_and_link_bulk_receipt(
    data: ReceiptCreateAndLinkBulk,
    database: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> ReceiptResponse:
    """Create a receipt and bulk-link it to multiple transactions (Sammelbeleg).

    Used from transactions → create receipt flow.
    Frontend: `/receipts/new?bulk_transaction_ids=xxx,yyy`

    Atomic: Receipt creation + all links in one DB transaction.
    """
    from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog

    # Load all requested transactions in one query
    transactions = database.scalars(
        select(Transaction).where(
            Transaction.id.in_(data.transaction_ids),
            Transaction.deleted_at.is_(None),
        )
    ).all()

    # Validate all transaction IDs exist
    found_ids = {tx.id for tx in transactions}
    not_found_ids = set(data.transaction_ids) - found_ids
    if not_found_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Transactions not found: {', '.join(sorted(not_found_ids)[:5])}{'...' if len(not_found_ids) > 5 else ''}",
        )

    # Create receipt (shared logic)
    receipt = _create_receipt_from_data(database, data, user.id)

    # Create all links
    for tx_id in data.transaction_ids:
        link = ReceiptTransactionLink(
            receipt_id=receipt.id,
            transaction_id=tx_id,
        )
        database.add(link)

    database.flush()

    # Update payment status atomically
    _update_payment_status(database, receipt)

    # Audit log
    database.add(
        ReceiptAuditLog(
            receipt_id=receipt.id,
            user_id=user.id,
            action=ReceiptAuditAction.LINKED,
            details={
                "bulk": True,
                "linked_count": len(data.transaction_ids),
                "transaction_ids": data.transaction_ids[:10],  # First 10 for audit
            },
        )
    )

    database.commit()

    receipt = _load_receipt_with_relationships(database, receipt.id)
    return build_receipt_response(receipt)


@router.get("/rc-compliance", response_model=RCComplianceSummary)
def get_rc_compliance_summary(
    date_from: date | None = Query(None, description="Start date (inclusive)"),
    date_to: date | None = Query(None, description="End date (inclusive)"),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> RCComplianceSummary:
    """Get Reverse Charge (§13b) compliance summary for a period.

    Returns summary of RC items to help determine UStVA filing requirements.
    Even Kleinunternehmer must file UStVA when §13b Reverse Charge applies.

    Kz.46: RC net total (Bemessungsgrundlage)
    Kz.47: RC tax total (USt auf RC)
    Kz.67: RC input tax (only for Regelbesteuert, empty for Kleinunternehmer)
    """

    from app.models.site_settings import SiteSettings

    # Get Kleinunternehmer status (None treated as False)
    site_settings = database.execute(select(SiteSettings).limit(1)).scalar_one_or_none()
    is_small_business = bool(site_settings.is_small_business) if site_settings and site_settings.is_small_business else False

    # Query receipts with line items
    query = select(ReceiptLineItem).join(Receipt).where(Receipt.deleted_at.is_(None))

    if date_from:
        query = query.where(Receipt.date >= date_from)
    if date_to:
        query = query.where(Receipt.date <= date_to)

    line_items = database.execute(query).scalars().all()

    # Filter for RC items and calculate totals
    rc_net_total = Decimal("0.00")
    rc_tax_total = Decimal("0.00")
    rc_input_tax_total = Decimal("0.00")
    rc_item_count = 0

    for item in line_items:
        if item.tax_rule.is_reverse_charge():
            rc_item_count += 1
            amount = abs(item.amount)
            rc_net_total += amount
            # Use persisted rc_tax_rate via property (GoBD: historical rate preserved)
            rc_tax = item.reverse_charge_tax_amount or Decimal("0.00")
            rc_tax_total += rc_tax
            if item.tax_rule.has_input_tax():
                rc_input_tax_total += rc_tax

    # Generate period label
    period_label = None
    if date_from and date_to:
        if date_from.month == date_to.month and date_from.year == date_to.year:
            period_label = f"{GERMAN_MONTHS[date_from.month - 1]} {date_from.year}"
        else:
            period_label = f"{GERMAN_MONTHS[date_from.month - 1]} – {GERMAN_MONTHS[date_to.month - 1]} {date_to.year}"

    return RCComplianceSummary(
        has_rc_items=rc_item_count > 0,
        rc_net_total=rc_net_total,
        rc_tax_total=rc_tax_total,
        rc_input_tax_total=rc_input_tax_total if not is_small_business else Decimal("0.00"),
        is_small_business=is_small_business,
        rc_item_count=rc_item_count,
        period_label=period_label,
    )


@router.get("/{receipt_id}", response_model=ReceiptResponse)
def get_receipt(
    receipt_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> ReceiptResponse:
    """Get a single receipt by ID."""
    receipt = _load_receipt_with_relationships(database, receipt_id)

    return build_receipt_response(receipt)


@router.patch("/{receipt_id}", response_model=ReceiptResponse)
def update_receipt(
    receipt_id: str,
    data: ReceiptUpdate,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> ReceiptResponse:
    """Update a draft receipt.

    Only draft receipts can be updated. Final and locked receipts return 403.
    """
    from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog

    receipt = _load_receipt_with_relationships(database, receipt_id, relationships=["line_items"])

    if receipt.status != ReceiptStatus.DRAFT:
        raise HTTPException(status_code=403, detail="Only draft receipts can be updated")

    try:
        require_unlocked(receipt)
    except ReceiptLockedError:
        raise HTTPException(status_code=403, detail="Locked receipts cannot be updated")

    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    changes = {}

    for field, value in update_data.items():
        if field == "line_items":
            continue  # Handle separately
        if hasattr(receipt, field) and getattr(receipt, field) != value:
            changes[field] = {"old": getattr(receipt, field), "new": value}
            setattr(receipt, field, value)

    # Handle line items update
    if data.line_items is not None:
        from app.core.constants import DEFAULT_RC_TAX_RATE
        from app.models.site_settings import SiteSettings

        # Get RC tax rate from SiteSettings for GoBD historical preservation
        settings = database.execute(select(SiteSettings).where(SiteSettings.id == 1)).scalar_one_or_none()
        rc_tax_rate = settings.rc_tax_rate if settings else DEFAULT_RC_TAX_RATE

        # Delete existing line items
        for li in receipt.line_items:
            database.delete(li)

        # Create new line items
        new_line_items = _create_line_items_from_request(receipt, data.line_items, rc_tax_rate)
        for li in new_line_items:
            database.add(li)

        changes["line_items"] = {"updated": True}

    if changes:
        database.add(
            ReceiptAuditLog(
                receipt_id=receipt.id,
                user_id=user.id,
                action=ReceiptAuditAction.UPDATED,
                details={"changes": {k: str(v) for k, v in changes.items()}},
            )
        )

    database.commit()

    receipt = _load_receipt_with_relationships(database, receipt.id)
    return build_receipt_response(receipt)


@router.post("/{receipt_id}/finalize", response_model=ReceiptResponse)
def finalize_receipt(
    receipt_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> ReceiptResponse:
    """Finalize a draft receipt (transition draft → final).

    This is irreversible. Validates all required fields are present.
    """
    from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog

    receipt = _load_receipt_with_relationships(database, receipt_id, relationships=["line_items"])

    if receipt.status == ReceiptStatus.FINAL:
        raise HTTPException(status_code=400, detail="Receipt is already final")

    # Validate required fields for finalization
    errors = []
    if not receipt.receipt_number:
        errors.append("receipt_number is required")
    if not receipt.counterparty:
        errors.append("counterparty is required")
    if not receipt.line_items:
        errors.append("At least one line item is required")

    if errors:
        raise HTTPException(status_code=422, detail=f"Cannot finalize: {', '.join(errors)}")

    receipt.status = ReceiptStatus.FINAL

    database.add(
        ReceiptAuditLog(
            receipt_id=receipt.id,
            user_id=user.id,
            action=ReceiptAuditAction.FINALIZED,
            details={},
        )
    )

    database.commit()

    # Learn accounting patterns from finalized receipt
    from app.services.category_suggestion import learn_from_receipt

    learn_from_receipt(database, receipt)

    receipt = _load_receipt_with_relationships(database, receipt.id)
    return build_receipt_response(receipt)


@router.post("/{receipt_id}/revert-to-draft", response_model=ReceiptResponse)
def revert_to_draft(
    receipt_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> ReceiptResponse:
    """Revert a final receipt back to draft (transition final → draft).

    Only allowed for unlocked receipts. Locked receipts are GoBD-immutable.
    """
    from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog

    receipt = _load_receipt_with_relationships(database, receipt_id, relationships=["line_items"])

    try:
        require_unlocked(receipt)
    except ReceiptLockedError:
        raise HTTPException(status_code=403, detail="Locked receipts cannot be reverted (GoBD)")

    if receipt.status != ReceiptStatus.FINAL:
        raise HTTPException(status_code=400, detail="Only final receipts can be reverted to draft")

    receipt.status = ReceiptStatus.DRAFT

    database.add(
        ReceiptAuditLog(
            receipt_id=receipt.id,
            user_id=user.id,
            action=ReceiptAuditAction.REVERTED,
            details={},
        )
    )

    database.commit()

    receipt = _load_receipt_with_relationships(database, receipt.id)
    return build_receipt_response(receipt)


@router.delete("/{receipt_id}", status_code=204)
def remove_receipt(
    receipt_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> None:
    """Delete a receipt.

    - Draft receipts: Hard delete allowed
    - Final receipts (not locked): Soft-delete only if not linked
    - Locked receipts: 403 Forbidden
    """
    from datetime import UTC, datetime

    from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog

    receipt = _load_receipt_with_relationships(database, receipt_id, relationships=["transaction_link"])

    try:
        require_unlocked(receipt)
    except ReceiptLockedError:
        raise HTTPException(status_code=403, detail="Locked receipts cannot be deleted (GoBD)")

    if receipt.transaction_links:
        tx_ids = [link.transaction_id for link in receipt.transaction_links]
        raise HTTPException(
            status_code=409,
            detail=f"Receipt is linked to {len(tx_ids)} transaction(s). Unlink first.",
        )

    if receipt.status == ReceiptStatus.DRAFT:
        # Hard delete for drafts — no audit log since it cascades with the receipt
        database.delete(receipt)
    else:
        # Soft delete for final receipts
        receipt.deleted_at = datetime.now(UTC)
        database.add(
            ReceiptAuditLog(
                receipt_id=receipt.id,
                user_id=user.id,
                action=ReceiptAuditAction.DELETED,
                details={"hard_delete": False},
            )
        )

    database.commit()


# --- Link/Unlink Endpoints ---


@router.post("/{receipt_id}/link", response_model=ReceiptResponse)
def link_receipt(
    receipt_id: str,
    request: ReceiptLinkRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> ReceiptResponse:
    """Link a receipt to a payment (transaction)."""
    try:
        receipt, _ = link_receipt_to_payment(database, receipt_id, request.transaction_id, user.id)
        database.commit()

        receipt = _load_receipt_with_relationships(database, receipt.id)
        return build_receipt_response(receipt)
    except ReceiptNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ReceiptLockedError as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.post("/{receipt_id}/unlink", response_model=ReceiptResponse)
def unlink_receipt(
    receipt_id: str,
    request: ReceiptUnlinkRequest | None = None,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> ReceiptResponse:
    """Unlink a receipt from a specific transaction, or all transactions if no body sent."""
    try:
        transaction_id = request.transaction_id if request else None
        receipt = unlink_receipt_from_payment(database, receipt_id, user.id, transaction_id)
        database.commit()

        receipt = _load_receipt_with_relationships(database, receipt.id)
        return build_receipt_response(receipt)
    except ReceiptNotFoundError:
        raise_not_found("Receipt", receipt_id)
    except ReceiptLockedError as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.post("/{receipt_id}/link-bulk")
def bulk_link_transactions(
    receipt_id: str,
    request: BulkLinkRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> BulkLinkResponse:
    """Bulk-link multiple transactions to a receipt (Sammelbeleg).

    Used for:
    - Etsy-PDF → 200 Fee-Transaktionen
    - PayPal-Gebührenabrechnung → N Fees

    Idempotent: already-linked transactions are skipped.
    """

    from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog

    # Load receipt
    receipt = _load_receipt_with_relationships(database, receipt_id, relationships=["line_items", "transaction_link"])

    try:
        require_unlocked(receipt)
    except ReceiptLockedError:
        raise HTTPException(status_code=403, detail="Locked receipts cannot be modified")

    # Get existing linked transaction IDs
    existing_linked_ids = {link.transaction_id for link in receipt.transaction_links}

    # Load all requested transactions in one query
    transactions = database.scalars(
        select(Transaction).where(
            Transaction.id.in_(request.transaction_ids),
            Transaction.deleted_at.is_(None),
        )
    ).all()

    # Validate all transaction IDs exist
    found_ids = {tx.id for tx in transactions}
    not_found_ids = set(request.transaction_ids) - found_ids
    if not_found_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Transactions not found: {', '.join(sorted(not_found_ids)[:5])}{'...' if len(not_found_ids) > 5 else ''}",
        )

    # Separate new vs already linked
    linked_count = 0
    skipped_count = 0
    new_transaction_ids = []

    for tx in transactions:
        if tx.id in existing_linked_ids:
            skipped_count += 1
        else:
            new_transaction_ids.append(tx.id)
            linked_count += 1

    # Create new links
    for tx_id in new_transaction_ids:
        link = ReceiptTransactionLink(
            receipt_id=receipt.id,
            transaction_id=tx_id,
        )
        database.add(link)

    # Update payment status
    if linked_count > 0:
        database.flush()  # Ensure links are visible
        _update_payment_status(database, receipt)

        # Audit log
        database.add(
            ReceiptAuditLog(
                receipt_id=receipt.id,
                user_id=user.id,
                action=ReceiptAuditAction.LINKED,
                details={
                    "bulk": True,
                    "linked_count": linked_count,
                    "skipped_count": skipped_count,
                    "transaction_ids": new_transaction_ids[:10],  # First 10 for audit
                },
            )
        )

    database.commit()

    # Reload to get updated state
    receipt = _load_receipt_with_relationships(database, receipt.id)

    # Calculate totals
    receipt_total = sum((abs(li.amount) for li in receipt.line_items), Decimal("0"))
    linked_tx_total = sum((abs(link.transaction.amount) for link in receipt.transaction_links), Decimal("0"))
    open_amount = max(Decimal("0.00"), receipt_total - linked_tx_total)
    amount_difference = receipt_total - linked_tx_total

    return build_bulk_link_response(linked_count, skipped_count, open_amount, amount_difference)


@router.post("/{receipt_id}/unlink-bulk")
def bulk_unlink_transactions(
    receipt_id: str,
    request: BulkUnlinkRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> BulkUnlinkResponse:
    """Bulk-unlink specific transactions from a receipt.

    Requires at least one transaction ID — empty list is rejected to prevent accidental mass-unlink.
    """
    from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog

    # Load receipt (line_items needed for payment_status calculation)
    receipt = _load_receipt_with_relationships(database, receipt_id, relationships=["line_items", "transaction_link"])

    try:
        require_unlocked(receipt)
    except ReceiptLockedError:
        raise HTTPException(status_code=403, detail="Locked receipts cannot be modified")

    # Determine which links to remove (empty list rejected by schema validation)
    links_to_remove = [link for link in receipt.transaction_links if link.transaction_id in request.transaction_ids]

    unlinked_count = len(links_to_remove)

    # Delete links
    for link in links_to_remove:
        database.delete(link)

    if unlinked_count > 0:
        database.flush()
        _update_payment_status(database, receipt)

        # Audit log
        database.add(
            ReceiptAuditLog(
                receipt_id=receipt.id,
                user_id=user.id,
                action=ReceiptAuditAction.UNLINKED,
                details={
                    "bulk": True,
                    "unlinked_count": unlinked_count,
                    "transaction_ids": [link.transaction_id for link in links_to_remove][:10],
                },
            )
        )

    database.commit()

    # Reload to get remaining links
    receipt = _load_receipt_with_relationships(database, receipt.id, relationships=["transaction_link"])
    remaining_link_count = len(receipt.transaction_links)

    return BulkUnlinkResponse(
        unlinked_count=unlinked_count,
        remaining_link_count=remaining_link_count,
    )


# --- Tag Endpoints ---


@router.get("/{receipt_id}/tags", response_model=list[TagResponse])
def get_receipt_tags(
    receipt_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> list[TagResponse]:
    """Get tags for a receipt."""
    receipt = _load_receipt_with_relationships(database, receipt_id, relationships=["tags"])
    return [TagResponse(id=tag.id, name=tag.name) for tag in receipt.tags]


@router.post("/{receipt_id}/tags", response_model=TagResponse, status_code=201)
def add_receipt_tag(
    receipt_id: str,
    tag_name: str = Query(..., min_length=1, max_length=100),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> TagResponse:
    """Add a tag to a receipt. Creates the tag if it doesn't exist."""
    from uuid import uuid4

    receipt = _load_receipt_with_relationships(database, receipt_id, relationships=["tags"])

    # Find or create tag
    tag = database.execute(
        select(Tag).where(
            Tag.name == tag_name,
        )
    ).scalar_one_or_none()

    if tag is None:
        tag = Tag(
            id=str(uuid4()),
            user_id=user.id,
            name=tag_name,
        )
        database.add(tag)

    # Check if already tagged
    if tag not in receipt.tags:
        receipt.tags.append(tag)

    database.commit()

    return TagResponse(id=tag.id, name=tag.name)


@router.delete("/{receipt_id}/tags/{tag_id}", status_code=204)
def remove_receipt_tag(
    receipt_id: str,
    tag_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> None:
    """Remove a tag from a receipt."""
    receipt = _load_receipt_with_relationships(database, receipt_id, relationships=["tags"])

    tag = database.execute(
        select(Tag).where(
            Tag.id == tag_id,
        )
    ).scalar_one_or_none()

    if tag is None:
        raise_not_found("Tag", tag_id)

    if tag in receipt.tags:
        receipt.tags.remove(tag)
        database.commit()


# --- Lock Endpoint ---


@router.post("/lock")
def lock_receipt_range(
    request: ReceiptLockRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> dict:
    """Lock all receipts in a date range (fiscal year finalization)."""
    count = lock_receipts(database, user.id, request.start_date, request.end_date)
    database.commit()
    return {"locked_count": count}


# --- File Download Endpoint ---


@router.get("/{receipt_id}/file")
def download_file(
    receipt_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> Response:
    """Download receipt file with integrity verification."""
    receipt = _load_receipt_with_relationships(database, receipt_id, relationships=[])

    if not receipt.file_storage_id or not receipt.file_hash:
        raise HTTPException(status_code=404, detail="Receipt has no file attached")

    try:
        content = get_file_content(receipt.file_storage_id, receipt.file_hash)
    except FileIntegrityError:
        raise HTTPException(status_code=500, detail="File integrity check failed")

    # Audit log for file download
    from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog

    database.add(
        ReceiptAuditLog(
            receipt_id=receipt.id,
            user_id=user.id,
            action=ReceiptAuditAction.FILE_DOWNLOADED,
            details={"object_name": receipt.file_storage_id},
        )
    )
    database.commit()

    return Response(
        content=content,
        media_type=receipt.file_mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": _build_content_disposition(receipt.file_original_name),
        },
    )


# --- File Upload Endpoint ---


@router.post("/{receipt_id}/upload", response_model=ReceiptResponse)
def upload_file(
    receipt_id: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> ReceiptResponse:
    """Upload a file to an existing receipt."""

    from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog

    receipt = _load_receipt_with_relationships(database, receipt_id, relationships=[])

    try:
        require_unlocked(receipt)
    except ReceiptLockedError:
        raise HTTPException(status_code=403, detail="Locked receipts cannot be modified")

    if file.filename is None:
        raise HTTPException(status_code=400, detail="Uploaded file must have a filename")

    try:
        file_content = file.file.read()
        file_hash, file_storage_id, file_mime_type = store_file(file_content, file.filename)
    except FileValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))

    receipt.file_hash = file_hash
    receipt.file_storage_id = file_storage_id
    receipt.file_original_name = file.filename
    receipt.file_mime_type = file_mime_type

    database.add(
        ReceiptAuditLog(
            receipt_id=receipt.id,
            user_id=user.id,
            action=ReceiptAuditAction.FILE_UPLOADED,
            details={"object_name": file_storage_id, "file_hash": file_hash},
        )
    )

    database.commit()

    receipt = _load_receipt_with_relationships(database, receipt.id)
    return build_receipt_response(receipt)


# --- Match Suggestions Endpoint ---


@router.get("/{receipt_id}/suggestions")
def get_suggestions(
    receipt_id: str,
    mode: Literal["single", "bulk"] = "single",
    source_config_id: str | None = Query(None, description="Filter by bank account (single mode)"),
    search: str | None = Query(None, description="Counterparty text search (single mode)"),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> list[ReceiptMatchSuggestion] | BulkSuggestionResponse:
    """Get payment suggestions for a receipt.

    mode=single: 1:1 match suggestions with confidence scoring.
    mode=bulk: Sammelbeleg suggestions — unlinked transactions from same source+month.
    """
    if mode == "bulk":
        return _get_bulk_suggestions(database, receipt_id)

    suggestions = suggest_matches_for_receipt(
        database,
        receipt_id,
        source_config_id=source_config_id,
        search=search,
    )

    return [
        ReceiptMatchSuggestion(
            id=s.id,
            counterparty=s.transaction_counterparty,
            source_config_name=s.source_config_name,
            amount=s.amount,
            date=date.fromisoformat(s.date),
            confidence=s.confidence,
            reasons=s.reasons or [],
        )
        for s in suggestions
    ]


def _get_bulk_suggestions(database: Session, receipt_id: str) -> BulkSuggestionResponse:
    """Get bulk-link suggestions for a Sammelbeleg (e.g., marketplace monthly invoice).

    Finds unlinked transactions from the same source and month as the receipt.
    Groups transactions by type (from extra_data.marketplace_type or parsed from description).
    """
    from collections import defaultdict

    from app.models.source import TransactionSourceConfig
    from app.schemas.receipt import TransactionGroup, TransactionSummary

    # Load receipt with relationships
    receipt = _load_receipt_with_relationships(database, receipt_id, relationships=["line_items", "transaction_link"])

    # Calculate receipt total
    receipt_total = sum((abs(li.amount) for li in receipt.line_items), Decimal("0"))

    # Determine source config ID:
    # 1. From existing links
    # 2. From receipt counterparty matching source name
    source_config_id = None
    if receipt.transaction_links:
        # Get source from first linked transaction
        first_link = receipt.transaction_links[0]
        if first_link.transaction and first_link.transaction.source_config_id:
            source_config_id = first_link.transaction.source_config_id
    else:
        # Try to match counterparty to source name
        source = database.execute(
            select(TransactionSourceConfig).where(
                TransactionSourceConfig.name.ilike(f"%{escape_like(receipt.counterparty)}%"),
            )
        ).scalar_one_or_none()
        if source:
            source_config_id = source.id

    if source_config_id is None:
        # No source found, return empty suggestions
        return BulkSuggestionResponse(
            transactions=[],
            groups=[],
            total=Decimal("0.00"),
            receipt_amount=receipt_total,
            difference=receipt_total,
            is_amount_matched=False,
            source_config_id=None,
        )

    # Get receipt month bounds
    receipt_month_start = receipt.date.replace(day=1)
    if receipt.date.month == 12:
        receipt_month_end = receipt.date.replace(year=receipt.date.year + 1, month=1, day=1)
    else:
        receipt_month_end = receipt.date.replace(month=receipt.date.month + 1, day=1)

    # Get existing linked transaction IDs (to exclude)
    existing_linked_ids = {link.transaction_id for link in receipt.transaction_links}

    # Find all unlinked transactions from this source in this month
    # A transaction is unlinked if it has no receipt_links
    subquery = select(ReceiptTransactionLink.transaction_id)
    unlinked_transactions = database.scalars(
        select(Transaction)
        .where(
            Transaction.source_config_id == source_config_id,
            Transaction.date >= receipt_month_start,
            Transaction.date < receipt_month_end,
            Transaction.deleted_at.is_(None),
            ~Transaction.id.in_(subquery),  # Not linked to any receipt
            ~Transaction.id.in_(existing_linked_ids),  # Not already linked to this receipt
            Transaction.is_internal_transfer.is_(False),  # Exclude payouts
        )
        .order_by(Transaction.date, Transaction.id)
    ).all()

    # Group transactions by type
    type_groups: defaultdict[str, list[Transaction]] = defaultdict(list)
    for tx in unlinked_transactions:
        # Get type from extra_data or description
        tx_type = "Other"
        if tx.extra_data and tx.extra_data.get("marketplace_type"):
            tx_type = tx.extra_data["marketplace_type"]
        elif tx.description:
            # Try to extract type from description (e.g., "Transaction fee", "Listing fee")
            desc_lower = tx.description.lower()
            if "transaction" in desc_lower:
                tx_type = "Transaction Fees"
            elif "processing" in desc_lower:
                tx_type = "Processing Fees"
            elif "listing" in desc_lower or "einstellgebühr" in desc_lower:
                tx_type = "Listing Fees"
            elif "ad" in desc_lower or "werbung" in desc_lower:
                tx_type = "Ads"
            elif "offsite" in desc_lower:
                tx_type = "Offsite Ads"
            elif "versand" in desc_lower or "shipping" in desc_lower:
                tx_type = "Shipping Labels"
        type_groups[tx_type].append(tx)

    # Build response
    transaction_summaries = [
        TransactionSummary(
            id=tx.id,
            date=tx.date,
            amount=tx.amount,
            counterparty=tx.counterparty,
            description=tx.description or "",
            type=tx.extra_data.get("marketplace_type") if tx.extra_data else None,
        )
        for tx in unlinked_transactions
    ]

    groups = [
        TransactionGroup(
            type=type_name,
            count=len(txs),
            total=sum((abs(tx.amount) for tx in txs), Decimal("0")),
            transaction_ids=[tx.id for tx in txs],
        )
        for type_name, txs in sorted(type_groups.items())
    ]

    total = sum((abs(tx.amount) for tx in unlinked_transactions), Decimal("0"))
    difference = receipt_total - total

    return BulkSuggestionResponse(
        transactions=transaction_summaries,
        groups=groups,
        total=total,
        receipt_amount=receipt_total,
        difference=difference,
        is_amount_matched=abs(difference) <= Decimal("0.02"),
        source_config_id=source_config_id,
    )


@router.post("/{receipt_id}/record-payment", response_model=ReceiptResponse, status_code=201)
def record_payment_for_receipt(
    receipt_id: str,
    data: RecordPaymentRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> ReceiptResponse:
    """Record a manual payment for a receipt.

    Creates a real transaction and links it to the receipt.
    Amount sign is determined by receipt type (expense → negative, revenue → positive).
    """
    from datetime import timedelta

    from app.services.receipt_service import record_payment

    # Validate date not too far in future
    today = date.today()
    if data.date > today + timedelta(days=1):
        raise HTTPException(status_code=400, detail="Payment date cannot be in the future")

    try:
        receipt, _transaction = record_payment(
            database=database,
            receipt_id=receipt_id,
            user_id=user.id,
            source_config_id=data.source_config_id,
            payment_date=data.date,
            amount=data.amount,
            counterparty=data.counterparty,
            description=data.description,
        )
    except ReceiptNotFoundError:
        raise_not_found("Receipt", receipt_id)
    except ReceiptLockedError:
        raise HTTPException(status_code=409, detail="Receipt is locked")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    database.commit()

    receipt = _load_receipt_with_relationships(database, receipt.id)
    return build_receipt_response(receipt)
