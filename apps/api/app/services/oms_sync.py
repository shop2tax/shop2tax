"""OMS receipt sync service (pull-based with bulk label dedup).

Provider-agnostic: works with any OmsProvider, operating only on generic OmsOrder
data. Sync flow:
1. Check precondition: is_small_business must be configured
2. Check concurrent lock (only one sync at a time)
3. Fetch orders via the provider
4. Filter out orders that already have the sync label
5. Process in chunks of 50:
   a. Fetch PDFs in parallel (rate-limited 2 req/s via AsyncLimiter)
   b. Create receipts sequentially (Session not concurrent-safe)
   c. Commit chunk + yield progress
6. Set sync labels in bulk via the provider
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from aiolimiter import AsyncLimiter
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.models.site_settings import SiteSettings
from app.models.sync_common import SyncResult
from app.services.oms_provider import OmsOrder, OmsProvider
from app.services.receipt_service import (
    DuplicateOmsReceiptError,
    ReceiptLineItemInput,
    StoredFileMetadata,
    create_revenue_receipt,
    determine_line_item_accounting,
)
from app.services.receipt_storage import store_file

logger = logging.getLogger(__name__)


class TaxSettingNotConfiguredError(Exception):
    """Raised when is_small_business setting has not been configured."""


class SyncAlreadyInProgressError(Exception):
    """Raised when a sync is already running (concurrent prevention)."""


# Module-level lock to prevent concurrent syncs (D-10)
_sync_lock = asyncio.Lock()


def _order_has_sync_label(order: OmsOrder, sync_label: str) -> bool:
    """Check if order already has the sync label."""
    return sync_label in order.tags


async def _fetch_pdf_rate_limited(
    limiter: AsyncLimiter,
    provider: OmsProvider,
    order: OmsOrder,
) -> tuple[OmsOrder, bytes | None, str | None]:
    """Fetch PDF with rate limiting. Returns (order, pdf_bytes, error)."""
    async with limiter:
        pdf_bytes, pdf_error = await provider.fetch_invoice_pdf(order.order_id)
        return order, pdf_bytes, pdf_error


async def sync_receipts_from_oms(
    provider: OmsProvider,
    provider_id: str,
    database: Session,
    user_id: str,
    store_ids: list[int] | None = None,
    min_order_date: datetime | None = None,
    max_order_date: datetime | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> SyncResult:
    """Sync receipts from OMS orders with chunked processing.

    Creates complete receipts with multiple line items (1:1 from order items),
    SKR03 account assignment based on tax settings, and the invoice PDF (fetched
    in parallel, rate-limited 2 req/s).

    Args:
        provider: The OMS provider to sync from
        provider_id: DB record ID of the provider (stored on created receipts)
        database: Database session
        user_id: User performing the sync
        store_ids: Optional filter by store IDs
        min_order_date: Only fetch orders created after this date
        max_order_date: Only fetch orders created before this date
        progress_callback: Optional callback for progress updates (streaming)

    Returns:
        SyncResult with counts and any errors

    Raises:
        TaxSettingNotConfiguredError: If is_small_business not set in SiteSettings
        SyncAlreadyInProgressError: If another sync is already running
    """
    settings = get_settings()
    sync_label = settings.billbee_sync_label
    result = SyncResult()

    # D-10: Concurrent sync prevention
    if _sync_lock.locked():
        raise SyncAlreadyInProgressError("Sync already in progress")
    await _sync_lock.acquire()

    try:
        return await _sync_receipts_internal(
            provider=provider,
            provider_id=provider_id,
            database=database,
            user_id=user_id,
            store_ids=store_ids,
            min_order_date=min_order_date,
            max_order_date=max_order_date,
            sync_label=sync_label,
            progress_callback=progress_callback,
            result=result,
        )
    finally:
        _sync_lock.release()


async def _sync_receipts_internal(
    provider: OmsProvider,
    provider_id: str,
    database: Session,
    user_id: str,
    store_ids: list[int] | None,
    min_order_date: datetime | None,
    max_order_date: datetime | None,
    sync_label: str,
    progress_callback: Callable[[dict[str, Any]], None] | None,
    result: SyncResult,
) -> SyncResult:
    """Internal sync implementation (called with lock held)."""
    # PRECONDITION: Check if tax setting is configured
    site_settings = database.execute(select(SiteSettings).where(SiteSettings.id == 1)).scalar_one_or_none()
    if site_settings is None or site_settings.is_small_business is None:
        raise TaxSettingNotConfiguredError("Bitte konfiguriere zuerst die Umsatzsteuer-Einstellung unter Einstellungen → Allgemein")

    is_small_business = site_settings.is_small_business
    set_labels_enabled = site_settings.oms_sync_set_labels

    # Step A: Fetch orders
    try:
        orders = await provider.fetch_orders(store_ids=store_ids, min_date=min_order_date, max_date=max_order_date)
    except Exception as error:
        logger.exception("Failed to fetch orders from OMS provider")
        result.errors.append(f"Failed to fetch orders: {type(error).__name__}")
        return result

    result.fetched_count = len(orders)

    # Step B: Filter orders (sync label, state, invoice)
    filtered_orders: list[OmsOrder] = []
    for order in orders:
        if _order_has_sync_label(order, sync_label):
            result.skipped_count += 1
            continue
        if order.state < 3:
            result.skipped_count += 1
            continue
        if not order.invoice_number:
            result.skipped_count += 1
            continue
        filtered_orders.append(order)

    total_to_process = len(filtered_orders)
    processed_count = 0
    successfully_imported_order_ids: list[str] = []

    # Step C: Process in chunks of 50
    chunk_size = 50
    # D-9: Rate limiter for PDF fetches (2 req/s, NOT Semaphore!)
    rate_limiter = AsyncLimiter(2, 1)

    for chunk_start in range(0, len(filtered_orders), chunk_size):
        chunk = filtered_orders[chunk_start : chunk_start + chunk_size]

        # C1: Fetch PDFs in parallel with rate limiter
        pdf_tasks = [_fetch_pdf_rate_limited(rate_limiter, provider, order) for order in chunk]
        pdf_results = await asyncio.gather(*pdf_tasks)

        # C2: Create receipts sequentially (Session not concurrent-safe)
        for order, pdf_bytes, pdf_error in pdf_results:
            try:
                receipt_created = await _create_receipt_from_order(
                    provider=provider,
                    provider_id=provider_id,
                    database=database,
                    user_id=user_id,
                    order=order,
                    pdf_bytes=pdf_bytes,
                    pdf_error=pdf_error,
                    is_small_business=is_small_business,
                    result=result,
                )
                if receipt_created:
                    successfully_imported_order_ids.append(order.order_id)
            except DuplicateOmsReceiptError:
                result.skipped_count += 1
            except Exception as error:
                logger.exception("Failed to create receipt for order %s", order.order_number)
                result.errors.append(f"Order {order.order_number}: {type(error).__name__}")

        # C3: Commit chunk
        database.commit()
        processed_count += len(chunk)

        # Report progress via callback
        if progress_callback:
            progress_callback(
                {
                    "type": "progress",
                    "processed": processed_count,
                    "total": total_to_process,
                    "imported": result.imported_count,
                    "skipped": result.skipped_count,
                    "errors": len(result.errors),
                }
            )

    # Step D: Bulk label setting (if enabled and any receipts imported)
    if set_labels_enabled and successfully_imported_order_ids:
        label_success, label_errors = await provider.set_labels(successfully_imported_order_ids, sync_label)
        if label_errors:
            result.errors.extend(label_errors)
        logger.info(f"Set sync labels on {label_success}/{len(successfully_imported_order_ids)} orders")

    return result


async def _create_receipt_from_order(
    provider: OmsProvider,
    provider_id: str,
    database: Session,
    user_id: str,
    order: OmsOrder,
    pdf_bytes: bytes | None,
    pdf_error: str | None,
    is_small_business: bool,
    result: SyncResult,
) -> bool:
    """Create a receipt from an OMS order. Returns True if created.

    Handles PDF storage errors gracefully (receipt still created without PDF).
    """
    # Build receipt number from invoice info
    receipt_number = order.invoice_number or order.order_number
    if order.invoice_number_prefix:
        receipt_number = f"{order.invoice_number_prefix}{receipt_number}"

    # Map order items to ReceiptLineItemInput with SKR03 assignment
    line_items: list[ReceiptLineItemInput] = []
    for item in order.items:
        skr03_account_id, tax_rule, tax_rate = determine_line_item_accounting(
            is_small_business=is_small_business,
            tax_rate_1=order.tax_rate_1,
            tax_rate_2=order.tax_rate_2,
            tax_index=item.tax_index,
            database=database,
        )
        line_items.append(
            ReceiptLineItemInput(
                description=item.product_title,
                amount=item.total_price,
                skr03_account_id=skr03_account_id,
                tax_rule=tax_rule,
                tax_rate=tax_rate,
            )
        )

    # Net-negative validation (for regular orders, not Stornos)
    line_item_sum = sum(item.amount for item in line_items)
    if order.total_cost >= Decimal("0") and line_item_sum < Decimal("0"):
        logger.warning(
            f"Order {order.order_number}: Line items sum to {line_item_sum} "
            f"but order total is {order.total_cost}. Skipping (likely discount > value)."
        )
        result.errors.append(f"Order {order.order_number}: Invalid line item sum (discount > order value)")
        result.skipped_count += 1
        return False

    # Handle PDF (graceful failure)
    file_metadata: StoredFileMetadata | None = None
    if pdf_error:
        logger.warning(f"PDF error for order {order.order_id}: {pdf_error}")
        result.errors.append(f"Order {order.order_number}: {pdf_error}")
        result.pdf_error_count += 1
    elif pdf_bytes:
        try:
            file_name = f"invoice_{order.invoice_number or order.order_number}.pdf"
            file_hash, file_storage_id, file_mime_type = await run_in_threadpool(store_file, pdf_bytes, file_name)
            file_metadata = StoredFileMetadata(
                file_hash=file_hash,
                file_storage_id=file_storage_id,
                file_mime_type=file_mime_type,
                file_original_name=file_name,
            )
            result.pdf_count += 1
        except Exception as storage_error:
            logger.warning(f"PDF storage failed for order {order.order_id}: {storage_error}")
            result.errors.append(f"Order {order.order_number}: PDF storage failed ({type(storage_error).__name__})")
            result.pdf_error_count += 1

    create_revenue_receipt(
        database=database,
        user_id=user_id,
        oms_order_id=order.order_id,
        receipt_number=receipt_number,
        receipt_date=order.created_at.date(),
        counterparty=order.customer_name,
        description=f"{provider.display_name} Order #{order.order_number}",
        line_items=line_items,
        file_metadata=file_metadata,
        oms_provider_id=provider_id,
        oms_invoice_number=order.invoice_number,
        oms_shop_name=order.shop_name,
        oms_platform=order.platform,
        payment_date=order.paid_at,
        source=provider.provider_type.value,
    )
    database.flush()

    result.imported_count += 1
    return True
