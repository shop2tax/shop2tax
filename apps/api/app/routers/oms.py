"""OMS (Order Management System) integration router."""

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.exceptions import raise_not_found
from app.core.pagination import PaginationParams, paginate_query
from app.database import get_db
from app.deps import CurrentUser, get_current_user
from app.models import OmsProviderRecord, OmsStore, OmsSyncLog, OmsSyncStatus, Transaction, User
from app.schemas.oms import (
    OmsBulkMatchRequest,
    OmsBulkMatchResponse,
    OmsLinkRequest,
    OmsMatchSuggestion,
    OmsOrderItemResponse,
    OmsOrderListResponse,
    OmsOrderResponse,
    OmsProviderInfoResponse,
    OmsSettingsResponse,
    OmsStoreCreate,
    OmsStoreResponse,
    OmsStoreUpdate,
    OmsSyncLogListResponse,
    OmsSyncLogResponse,
)
from app.services.oms_provider import OmsOrder, OmsProvider, get_oms_provider, get_oms_providers
from app.services.receipt_service import auto_link_by_oms_order_id
from app.services.response_builders import (
    build_oms_settings_response,
    build_oms_store_response,
    build_oms_sync_log_response,
    build_transaction_response,
)

router = APIRouter(prefix="/api/v1/oms", tags=["oms"])

logger = logging.getLogger(__name__)


def _get_db_user(
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> User:
    """Fetch the full ORM User from DB (needed for encrypted credential access)."""
    db_user = session.get(User, user.id)
    if not db_user:
        raise_not_found("User", user.id)
    return db_user


def _require_provider(session: Session) -> tuple[OmsProvider, str]:
    """Resolve the default active OMS provider and its record ID.

    Raises HTTPException 400 (German UI message) when no provider is configured
    or its credentials are missing from the environment.
    """
    record = session.scalars(select(OmsProviderRecord).where(OmsProviderRecord.is_active).order_by(OmsProviderRecord.display_name)).first()
    if record is None:
        raise HTTPException(status_code=400, detail="Keine Warenwirtschaft konfiguriert.")
    provider = get_oms_provider(record.id, session)
    if provider is None:
        raise HTTPException(
            status_code=400,
            detail=f"{record.display_name}-Zugangsdaten nicht konfiguriert.",
        )
    return provider, record.id


def _store_ids(session: Session) -> list[int] | None:
    """Collect external shop IDs from configured stores (None if none)."""
    stores = session.scalars(select(OmsStore)).all()
    return [store.external_shop_id for store in stores] if stores else None


def _to_order_response(order: OmsOrder) -> OmsOrderResponse:
    """Map a generic OmsOrder to its API response schema."""
    return OmsOrderResponse(
        order_id=order.order_id,
        order_number=order.order_number,
        invoice_number=order.invoice_number,
        invoice_number_prefix=order.invoice_number_prefix,
        state=order.state,
        created_at=order.created_at,
        total_cost=order.total_cost,
        currency=order.currency,
        customer_name=order.customer_name,
        customer_email=order.customer_email,
        shop_id=order.shop_id,
        shop_name=order.shop_name,
        platform=order.platform,
        items=[
            OmsOrderItemResponse(
                product_title=item.product_title,
                quantity=item.quantity,
                total_price=item.total_price,
                sku=item.sku,
                tax_index=item.tax_index,
                tax_amount=item.tax_amount,
            )
            for item in order.items
        ],
        tags=order.tags,
        paid_amount=order.paid_amount,
        is_paid=order.is_paid,
        paid_at=order.paid_at,
        tax_rate_1=order.tax_rate_1,
        tax_rate_2=order.tax_rate_2,
    )


# --- Provider Endpoints ---


@router.get("/providers", response_model=list[OmsProviderInfoResponse])
def list_providers(
    session: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> list[OmsProviderInfoResponse]:
    """List all active OMS providers (used by the frontend to enable features dynamically)."""
    return [
        OmsProviderInfoResponse(id=info.id, type=info.type, display_name=info.display_name, is_active=info.is_active)
        for info in get_oms_providers(session)
    ]


# --- Settings Endpoints ---


@router.get("/settings", response_model=OmsSettingsResponse)
def get_oms_settings(
    session: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> OmsSettingsResponse:
    """Get OMS integration settings."""
    from app.config import get_settings

    stores = session.scalars(select(OmsStore).options(joinedload(OmsStore.source_config)).order_by(OmsStore.label)).unique().all()

    settings = get_settings()
    has_credentials = bool(settings.billbee_username and settings.billbee_password)

    return build_oms_settings_response(has_credentials, stores)


# --- Store Mapping Endpoints ---


def _default_provider_id(session: Session) -> str | None:
    """Record ID of the default active provider (for store auto-assignment)."""
    record = session.scalars(select(OmsProviderRecord).where(OmsProviderRecord.is_active).order_by(OmsProviderRecord.display_name)).first()
    return record.id if record else None


@router.post("/stores", response_model=OmsStoreResponse, status_code=201)
def create_store(
    request: OmsStoreCreate,
    session: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> OmsStoreResponse:
    """Create a new OMS store mapping."""
    store = OmsStore(
        user_id=user.id,
        provider_id=request.provider_id or _default_provider_id(session),
        store_type=request.store_type,
        label=request.label,
        external_shop_id=request.external_shop_id,
        source_config_id=request.source_config_id,
        match_strategy=request.match_strategy,
    )
    session.add(store)
    session.commit()
    session.refresh(store)
    return build_oms_store_response(store)


@router.put("/stores/{store_id}", response_model=OmsStoreResponse)
def update_store(
    store_id: str,
    request: OmsStoreUpdate,
    session: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> OmsStoreResponse:
    """Update an existing OMS store mapping."""
    store = session.scalars(select(OmsStore).options(joinedload(OmsStore.source_config)).where(OmsStore.id == store_id)).first()

    if not store:
        raise_not_found("Store", store_id)

    if request.store_type is not None:
        store.store_type = request.store_type
    if request.label is not None:
        store.label = request.label
    if request.external_shop_id is not None:
        store.external_shop_id = request.external_shop_id
    if request.provider_id is not None:
        store.provider_id = request.provider_id
    if request.source_config_id is not None:
        # Validate source type is MARKETPLACE_MAPPING
        if request.source_config_id:
            from app.models.source import SourceType, TransactionSourceConfig

            source_config = session.scalar(select(TransactionSourceConfig).where(TransactionSourceConfig.id == request.source_config_id))
            if source_config is None:
                raise_not_found("Source config", request.source_config_id)
            if source_config.type != SourceType.MARKETPLACE_MAPPING:
                raise HTTPException(
                    status_code=400,
                    detail="Store can only be linked to MARKETPLACE_MAPPING sources",
                )
        store.source_config_id = request.source_config_id
    if request.match_strategy is not None:
        store.match_strategy = request.match_strategy

    session.commit()
    session.refresh(store)
    return build_oms_store_response(store)


@router.delete("/stores/{store_id}", status_code=204)
def delete_store(
    store_id: str,
    session: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Delete an OMS store mapping."""
    store = session.scalars(select(OmsStore).where(OmsStore.id == store_id)).first()

    if not store:
        raise_not_found("Store", store_id)

    session.delete(store)
    session.commit()


# --- Orders Endpoints ---


@router.get("/orders", response_model=OmsOrderListResponse)
async def list_orders(
    force_refresh: bool = Query(False, description="Force cache refresh"),
    session: Session = Depends(get_db),
    user: User = Depends(_get_db_user),
) -> OmsOrderListResponse:
    """List orders from the OMS provider with 2-hour caching."""
    provider, _ = _require_provider(session)

    orders, is_cached, expires_at = await provider.fetch_orders_cached(
        store_ids=_store_ids(session),
        force_refresh=force_refresh,
    )

    return OmsOrderListResponse(
        items=[_to_order_response(order) for order in orders],
        total=len(orders),
        cached=is_cached,
        cache_expires_at=expires_at,
    )


@router.get("/orders/{order_id}", response_model=OmsOrderResponse)
async def get_order(
    order_id: str,
    session: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> OmsOrderResponse:
    """Get a single OMS order by ID."""
    provider, _ = _require_provider(session)

    order = await provider.fetch_order_by_id(order_id)
    if not order:
        raise_not_found("Order", order_id)

    return _to_order_response(order)


# --- Matching & Linking Endpoints ---


@router.get("/match/{transaction_id}", response_model=list[OmsMatchSuggestion])
async def find_matches_for_transaction(
    transaction_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(_get_db_user),
) -> list[OmsMatchSuggestion]:
    """Find potential OMS order matches for a transaction."""
    from app.services.oms_matching import find_matching_orders

    provider, _ = _require_provider(session)

    transaction = session.scalars(select(Transaction).where(Transaction.id == transaction_id, Transaction.deleted_at.is_(None))).first()
    if not transaction:
        raise_not_found("Transaction", transaction_id)

    orders, _, _ = await provider.fetch_orders_cached(store_ids=_store_ids(session))

    matches = find_matching_orders(
        orders=orders,
        amount=transaction.amount,
        transaction_date=datetime.combine(transaction.date, datetime.min.time()),
        counterparty=transaction.counterparty,
    )

    return [
        OmsMatchSuggestion(
            oms_order_id=match.oms_order_id,
            order_number=match.order_number,
            confidence=match.confidence,
            match_reasons=match.match_reasons,
            order_amount=match.order_amount,
            order_date=match.order_date,
            customer_name=match.customer_name,
        )
        for match in matches
    ]


@router.post("/link/{transaction_id}")
async def link_transaction_to_order(
    transaction_id: str,
    request: OmsLinkRequest,
    session: Session = Depends(get_db),
    user: User = Depends(_get_db_user),
):
    """Link a transaction to an OMS order.

    Supports partial payment tracking:
    - If amount_covered is provided, uses that as the payment amount
    - Otherwise uses the transaction amount
    - Calculates remaining_amount from the OMS order total
    """
    provider, _ = _require_provider(session)

    transaction = session.scalars(select(Transaction).where(Transaction.id == transaction_id, Transaction.deleted_at.is_(None))).first()
    if not transaction:
        raise_not_found("Transaction", transaction_id)

    # Fetch order to get total amount for partial payment calculation
    order = await provider.fetch_order_by_id(request.oms_order_id)

    amount_covered = request.amount_covered or abs(transaction.amount)
    if order:
        remaining = order.total_cost - amount_covered
        transaction.remaining_amount = remaining if remaining > 0 else None
    else:
        transaction.remaining_amount = None

    transaction.oms_order_id = request.oms_order_id
    session.commit()
    session.refresh(transaction)

    return build_transaction_response(transaction)


@router.delete("/link/{transaction_id}")
def unlink_transaction_from_order(
    transaction_id: str,
    session: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Remove the OMS order link from a transaction."""
    transaction = session.scalars(select(Transaction).where(Transaction.id == transaction_id, Transaction.deleted_at.is_(None))).first()
    if not transaction:
        raise_not_found("Transaction", transaction_id)

    transaction.oms_order_id = None
    transaction.remaining_amount = None
    session.commit()
    session.refresh(transaction)

    return build_transaction_response(transaction)


@router.post("/cache/clear")
def clear_order_cache(
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, int]:
    """Clear the OMS orders cache."""
    from app.services.providers.billbee import clear_cache

    return {"cleared_entries": clear_cache()}


# --- Bulk Matching Endpoint ---


@router.post("/match-bulk", response_model=OmsBulkMatchResponse)
async def bulk_match_transactions(
    request: OmsBulkMatchRequest,
    session: Session = Depends(get_db),
    user: User = Depends(_get_db_user),
) -> OmsBulkMatchResponse:
    """Bulk-match unmatched transactions to OMS orders.

    Relation rules:
    - Amazon/Etsy/Shopify: match source_reference -> order_number
    - Stripe: match counterparty (email) -> customer_email
    - Bank sources: skipped (no OMS relation)
    """
    from sqlalchemy import and_

    from app.models.source import TransactionSourceConfig
    from app.services.oms_matching import build_order_lookup, match_transaction_to_order

    provider, _ = _require_provider(session)

    stores = session.scalars(select(OmsStore)).all()
    store_ids = [store.external_shop_id for store in stores] if stores else None

    orders, _, _ = await provider.fetch_orders_cached(store_ids=store_ids)

    order_number_lookup, email_lookup = build_order_lookup(orders)

    # Build source_config_id -> match_strategy lookup from store links
    strategy_by_source_config: dict[str, str] = {}
    for store in stores:
        if store.source_config_id:
            strategy_by_source_config[store.source_config_id] = store.match_strategy

    # Sources that can be matched to OMS orders (by name, lowercase)
    matchable_source_names = {"etsy", "amazon", "shopify", "stripe"}
    if request.sources:
        matchable_source_names = {source.lower() for source in request.sources} & matchable_source_names

    conditions = [Transaction.deleted_at.is_(None)]
    if not request.overwrite_existing:
        conditions.append(Transaction.oms_order_id.is_(None))

    query = select(Transaction).where(and_(*conditions)).join(TransactionSourceConfig, isouter=True)
    transactions = session.scalars(query).all()

    matched_count = 0
    unmatched_count = 0
    skipped_count = 0
    matched_transaction_ids: list[str] = []

    for transaction in transactions:
        source_name = transaction.source_config.name.lower() if transaction.source_config else None
        if source_name not in matchable_source_names:
            skipped_count += 1
            continue

        strategy = strategy_by_source_config.get(transaction.source_config_id or "", "order_number")
        if not transaction.source_config_id and source_name == "stripe":
            strategy = "email"

        matched_order = match_transaction_to_order(
            order_number_lookup=order_number_lookup,
            email_lookup=email_lookup,
            match_strategy=strategy,
            source_reference=transaction.source_reference,
            counterparty=transaction.counterparty,
        )

        if matched_order:
            enrichment = provider.enrich_transaction(matched_order)
            transaction.oms_order_id = matched_order.order_id
            if enrichment.customer_name:
                transaction.counterparty = enrichment.customer_name
            if enrichment.invoice_number:
                transaction.description = enrichment.invoice_number
            matched_count += 1
            matched_transaction_ids.append(transaction.id)
        else:
            unmatched_count += 1

    session.commit()

    return OmsBulkMatchResponse(
        matched_count=matched_count,
        unmatched_count=unmatched_count,
        skipped_count=skipped_count,
        matched_transaction_ids=matched_transaction_ids,
    )


# --- Sync Endpoints ---


@router.post("/sync")
async def sync_receipts(
    start_date: date | None = Query(
        default=None,
        description="Only sync orders after this date. Defaults to last sync date or 2026-01-01.",
    ),
    end_date: date | None = Query(
        default=None,
        description="Only sync orders before this date. Defaults to today.",
    ),
    session: Session = Depends(get_db),
    db_user: User = Depends(_get_db_user),
) -> StreamingResponse:
    """Sync receipts from OMS orders with streaming progress (NDJSON)."""
    import asyncio
    import json
    from collections.abc import AsyncIterator
    from datetime import timezone

    from app.models.sync_common import SyncResult
    from app.services.oms_sync import (
        TAX_SETTING_NOT_CONFIGURED_MESSAGE,
        SyncAlreadyInProgressError,
        TaxSettingNotConfiguredError,
        _sync_lock,
        sync_receipts_from_oms,
    )

    provider, provider_id = _require_provider(session)

    # Resolve end_date: explicit > today
    today = date.today()
    resolved_end_date = end_date or today

    if end_date and end_date > today:
        raise HTTPException(status_code=400, detail="end_date cannot be in the future")

    # Determine start date: explicit > last sync > default (Jan 1 current year)
    if start_date:
        min_order_date = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    else:
        last_log = session.scalars(select(OmsSyncLog).order_by(OmsSyncLog.created_at.desc()).limit(1)).first()
        if last_log:
            min_order_date = last_log.end_date
        else:
            min_order_date = datetime(2026, 1, 1, tzinfo=timezone.utc)

    if start_date and resolved_end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")

    max_order_date = datetime(
        resolved_end_date.year,
        resolved_end_date.month,
        resolved_end_date.day,
        23,
        59,
        59,
        tzinfo=timezone.utc,
    )

    # Check lock BEFORE creating StreamingResponse -> real HTTP 409
    if _sync_lock.locked():
        raise HTTPException(status_code=409, detail="Sync already in progress")

    progress_queue: asyncio.Queue[dict | None] = asyncio.Queue()

    def progress_callback(event: dict) -> None:
        progress_queue.put_nowait(event)

    async def run_sync() -> SyncResult:
        """Run sync and signal completion via sentinel on the queue."""
        try:
            return await sync_receipts_from_oms(
                provider=provider,
                provider_id=provider_id,
                database=session,
                user_id=db_user.id,
                min_order_date=min_order_date,
                max_order_date=max_order_date,
                progress_callback=progress_callback,
            )
        finally:
            progress_queue.put_nowait(None)  # Sentinel: sync done

    async def generate_stream() -> AsyncIterator[str]:
        """Generate NDJSON stream with live progress events and final result."""
        sync_task = asyncio.create_task(run_sync())

        while True:
            event = await progress_queue.get()
            if event is None:  # Sentinel: sync finished
                break
            yield json.dumps(event) + "\n"

        try:
            result = sync_task.result()
        except SyncAlreadyInProgressError:
            yield json.dumps({"type": "error", "error": "Sync läuft bereits"}) + "\n"
            return
        except TaxSettingNotConfiguredError:
            yield json.dumps({"type": "error", "error": TAX_SETTING_NOT_CONFIGURED_MESSAGE}) + "\n"
            return
        except Exception:
            logger.exception("OMS sync failed")
            yield json.dumps({"type": "error", "error": "Sync unerwartet fehlgeschlagen – Details im Server-Log"}) + "\n"
            return

        if result.errors:
            status = OmsSyncStatus.PARTIAL if result.imported_count > 0 else OmsSyncStatus.FAILED
        else:
            status = OmsSyncStatus.SUCCESS

        sync_log = OmsSyncLog(
            user_id=db_user.id,
            start_date=min_order_date,
            end_date=datetime(resolved_end_date.year, resolved_end_date.month, resolved_end_date.day, tzinfo=timezone.utc),
            fetched_count=result.fetched_count,
            imported_count=result.imported_count,
            skipped_count=result.skipped_count,
            status=status,
            error_message="; ".join(result.errors) if result.errors else None,
        )
        session.add(sync_log)
        session.commit()

        # Bidirectional auto-link: newly synced receipts -> existing unlinked transactions (non-fatal)
        linked_count = 0
        try:
            link_result = auto_link_by_oms_order_id(session, db_user.id)
            session.commit()
            linked_count = link_result.linked
            logger.info(
                "Auto-link after OMS sync: linked=%d, no_receipt=%d, skipped_locked=%d",
                link_result.linked,
                link_result.no_receipt,
                link_result.skipped_locked,
            )
        except Exception as error:
            logger.warning(f"Auto-link after OMS sync failed (sync preserved): {error}")
            session.rollback()

        complete_event = {
            "type": "complete",
            "imported_count": result.imported_count,
            "skipped_count": result.skipped_count,
            "pdf_count": result.pdf_count,
            "pdf_error_count": result.pdf_error_count,
            "linked_count": linked_count,
            "errors": result.errors,
        }
        yield json.dumps(complete_event) + "\n"

    return StreamingResponse(generate_stream(), media_type="application/x-ndjson")


@router.get("/sync/last", response_model=OmsSyncLogResponse | None)
def get_last_sync(
    session: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> OmsSyncLogResponse | None:
    """Get the most recent sync log entry."""
    log = session.scalars(select(OmsSyncLog).order_by(OmsSyncLog.created_at.desc()).limit(1)).first()
    if not log:
        return None
    return build_oms_sync_log_response(log)


@router.get("/sync/history", response_model=OmsSyncLogListResponse)
def get_sync_history(
    pagination: PaginationParams = Depends(),
    session: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> OmsSyncLogListResponse:
    """Get paginated sync history."""
    statement = select(OmsSyncLog).order_by(OmsSyncLog.created_at.desc(), OmsSyncLog.id.desc())
    items, total = paginate_query(session, statement, pagination)

    return OmsSyncLogListResponse(
        items=[build_oms_sync_log_response(log) for log in items],
        total=total,
    )
