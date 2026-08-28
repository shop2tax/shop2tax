"""Centralized response builders for API endpoints.

Single source of truth for converting ORM models to Pydantic response schemas.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.accounting_pattern import AccountingPattern
    from app.models.export_log import ExportLog
    from app.models.oms_store import OmsStore
    from app.models.oms_sync_log import OmsSyncLog
    from app.models.paypal_sync_log import PayPalSyncLog
    from app.models.source import CsvMappingProfile, TransactionSourceConfig
    from app.models.sync_common import SyncResult
    from app.schemas.datev import ExportLogResponse
    from app.schemas.oms import OmsSettingsResponse, OmsStoreResponse, OmsSyncLogResponse
    from app.schemas.paypal import PayPalSyncLogResponse, PayPalSyncResponse
    from app.schemas.receipt import AccountSuggestionResponse, BulkLinkResponse
    from app.schemas.source import CsvMappingProfileResponse, TransactionSourceConfigResponse

from app.models.receipt import Receipt
from app.models.receipt_line_item import ReceiptLineItem
from app.models.skr03 import SKR03Account
from app.models.transaction import Transaction
from app.schemas.receipt import (
    LinkedTransactionSummary,
    ReceiptLineItemResponse,
    ReceiptResponse,
    TagResponse,
)
from app.schemas.skr03 import SKR03AccountResponse
from app.schemas.transaction import (
    LinkedReceiptSummary,
    TransactionResponse,
    TransactionStatus,
)


def build_receipt_line_item_response(line_item: ReceiptLineItem) -> ReceiptLineItemResponse:
    """Build ReceiptLineItemResponse from ORM model."""
    account = line_item.skr03_account
    return ReceiptLineItemResponse(
        id=line_item.id,
        position=line_item.position,
        description=line_item.description,
        amount=line_item.amount,
        skr03_account_id=line_item.skr03_account_id,
        skr03_account_number=account.id if account else None,
        skr03_account_name=account.name if account else None,
        tax_rule=line_item.tax_rule,
        tax_rate=line_item.tax_rate,
        depreciation=line_item.depreciation,
        # RC computed fields
        reverse_charge_tax_amount=line_item.reverse_charge_tax_amount,
        effective_tax_rate=line_item.effective_tax_rate,
    )


def _compute_transaction_status(
    transaction: Transaction,
    linked_receipts_count: int,
    open_amount: Decimal,
) -> TransactionStatus:
    """Compute transaction status based on receipts and flags.

    Status priority:
    1. PRIVATE: is_private flag set
    2. INTERNAL: is_internal_transfer flag set
    3. OPEN: No linked receipts
    4. ASSIGNED: Has receipts but open_amount > 0
    5. AUTOMATIC: oms_order_id present (auto-matched)
    6. BOOKED: open_amount = 0
    """
    if transaction.is_private:
        return TransactionStatus.PRIVATE

    if transaction.is_internal_transfer:
        return TransactionStatus.INTERNAL

    if linked_receipts_count == 0:
        return TransactionStatus.OPEN

    if open_amount > 0:
        return TransactionStatus.ASSIGNED

    # open_amount == 0 (fully booked)
    if transaction.oms_order_id:
        return TransactionStatus.AUTOMATIC

    return TransactionStatus.BOOKED


def build_transaction_response(transaction: Transaction) -> TransactionResponse:
    """Build TransactionResponse from ORM model.

    Uses receipt_links (junction table) instead of direct receipt FK.
    Computes status and open_amount.
    """
    # Get linked receipt info from junction table
    linked_receipts: list[LinkedReceiptSummary] = []
    transaction_abs = abs(transaction.amount)
    total_receipt_contribution = Decimal("0.00")

    for link in transaction.receipt_links:
        receipt = link.receipt
        # Sum line items for receipt amount
        receipt_amount = sum((li.amount for li in receipt.line_items), Decimal("0.00"))

        linked_receipts.append(
            LinkedReceiptSummary(
                id=receipt.id,
                receipt_number=receipt.receipt_number,
                counterparty=receipt.counterparty,
                amount=receipt_amount,
                date=receipt.date,
                type=receipt.type,
                has_file=receipt.file_hash is not None,
            )
        )
        # Sammelbeleg: receipt covers many transactions → cap contribution at transaction amount
        total_receipt_contribution += min(receipt_amount, transaction_abs)

    # Compute open_amount: how much of transaction is not yet covered by receipts
    open_amount = max(transaction_abs - total_receipt_contribution, Decimal("0.00"))

    # Compute status
    status = _compute_transaction_status(transaction, len(linked_receipts), open_amount)

    # Get source config info
    source_config = transaction.source_config

    return TransactionResponse(
        id=transaction.id,
        date=transaction.date,
        amount=transaction.amount,
        counterparty=transaction.counterparty,
        description=transaction.description,
        source_reference=transaction.source_reference,
        oms_order_id=transaction.oms_order_id,
        notes=transaction.notes,
        is_private=transaction.is_private,
        remaining_amount=transaction.remaining_amount,
        original_currency=transaction.original_currency,
        original_amount=transaction.original_amount,
        exchange_rate=transaction.exchange_rate,
        source_config_id=transaction.source_config_id,
        source_config_name=source_config.name if source_config else None,
        status=status,
        open_amount=open_amount,
        linked_receipts=linked_receipts,
        is_internal_transfer=transaction.is_internal_transfer,
        linked_transfer_id=transaction.linked_transfer_id,
        created_at=transaction.created_at,
        updated_at=transaction.updated_at,
    )


def build_skr03_account_response(account: SKR03Account) -> SKR03AccountResponse:
    """Build SKR03AccountResponse from ORM model."""
    return SKR03AccountResponse(
        id=account.id,
        name=account.name,
        category=account.category,
        active=account.active,
        bu_schluessel=account.bu_schluessel,
        is_system=account.is_system,
    )


def build_receipt_response(receipt: Receipt) -> ReceiptResponse:
    """Build ReceiptResponse from ORM model.

    Includes line items, tags, and linked transaction info.
    Amount is always computed from line items (sum).
    """
    # Build line items
    line_items = [build_receipt_line_item_response(li) for li in receipt.line_items]

    # Build tags
    tags = [TagResponse(id=tag.id, name=tag.name) for tag in receipt.tags]

    # Compute total amount from line items
    total_amount = sum((li.amount for li in receipt.line_items), Decimal("0.00"))

    # Get all linked transactions from junction table (M:N)
    linked_transactions: list[LinkedTransactionSummary] = []
    linked_amount = Decimal("0.00")

    for link in receipt.transaction_links:
        if link.transaction:
            tx = link.transaction
            linked_amount += abs(tx.amount)
            linked_transactions.append(
                LinkedTransactionSummary(
                    id=tx.id,
                    date=tx.date,
                    amount=tx.amount,
                    counterparty=tx.counterparty,
                    source_config_name=tx.source_config.name if tx.source_config else None,
                )
            )

    # Backwards compat: first linked transaction (deprecated, use linked_transactions)
    linked_transaction_id = linked_transactions[0].id if linked_transactions else None
    linked_transaction = linked_transactions[0] if linked_transactions else None

    # Open amount: receipt total - sum of linked transaction amounts (clamped to 0)
    open_amount = max(total_amount - linked_amount, Decimal("0.00"))

    return ReceiptResponse(
        id=receipt.id,
        type=receipt.type,
        status=receipt.status,
        receipt_number=receipt.receipt_number,
        date=receipt.date,
        amount=total_amount,
        counterparty=receipt.counterparty,
        description=receipt.description,
        due_date=receipt.due_date,
        payment_date=receipt.payment_date,
        delivery_date=receipt.delivery_date,
        delivery_period=receipt.delivery_period,
        currency=receipt.currency,
        extraction_source=receipt.extraction_source,
        line_items=line_items,
        tags=tags,
        payment_status=receipt.payment_status,
        open_amount=open_amount,
        oms_order_id=receipt.oms_order_id,
        oms_invoice_number=receipt.oms_invoice_number,
        oms_shop_name=receipt.oms_shop_name,
        oms_platform=receipt.oms_platform,
        has_file=receipt.file_storage_id is not None,
        file_original_name=receipt.file_original_name,
        file_mime_type=receipt.file_mime_type,
        is_locked=receipt.is_locked,
        locked_at=receipt.locked_at,
        linked_transaction_id=linked_transaction_id,
        linked_transaction=linked_transaction,
        linked_transactions=linked_transactions,
        # RC aggregates
        total_reverse_charge_tax=receipt.total_reverse_charge_tax,
        has_reverse_charge_items=receipt.has_reverse_charge_items,
        created_at=receipt.created_at,
        updated_at=receipt.updated_at,
    )


def build_source_config_response(source: "TransactionSourceConfig") -> "TransactionSourceConfigResponse":
    """Build TransactionSourceConfigResponse from ORM model."""
    from app.models.source import SourceType
    from app.schemas.source import MarketplaceSourceConfig, TransactionSourceConfigResponse

    # Shared tenant: mapping exists for this source (not per-user)
    has_mapping = source.mapping_profile is not None

    # Extract marketplace config if present
    marketplace_config = None
    if source.type == SourceType.MARKETPLACE_MAPPING and source.source_config:
        marketplace_config = MarketplaceSourceConfig(
            parser=source.source_config.get("parser"),
            has_ust_id_registered=source.source_config.get("has_ust_id_registered", True),
        )

    # Determine import method based on source type and config
    if source.type == SourceType.CSV_PARSER:
        import_method = "CSV-Parser (automatisch)"
    elif source.type == SourceType.API_SYNC:
        import_method = "API-Sync"
    elif source.type == SourceType.CSV_MAPPING:
        import_method = "CSV-Zuordnung (konfiguriert)" if has_mapping else "CSV-Zuordnung (nicht konfiguriert)"
    elif source.type == SourceType.MARKETPLACE_MAPPING:
        # Show parser name if configured
        if marketplace_config and marketplace_config.parser:
            import_method = f"{marketplace_config.parser.capitalize()}-Parser"
        elif has_mapping:
            import_method = "Marktplatz-Zuordnung (konfiguriert)"
        else:
            import_method = "Marktplatz-Zuordnung (nicht konfiguriert)"
    else:
        import_method = "Nicht konfiguriert"

    return TransactionSourceConfigResponse(
        id=source.id,
        name=source.name,
        type=source.type,
        check_account_id=source.check_account_id,
        is_system=source.user_id is None,
        has_mapping=has_mapping,
        import_method=import_method,
        source_config=marketplace_config,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def build_mapping_profile_response(mapping: "CsvMappingProfile") -> "CsvMappingProfileResponse":
    """Build CsvMappingProfileResponse from ORM model."""
    from app.schemas.source import CsvMappingProfileResponse

    return CsvMappingProfileResponse(
        id=mapping.id,
        source_id=mapping.source_id,
        source_name=mapping.source_config.name,
        name=mapping.name,
        delimiter=mapping.delimiter,
        encoding=mapping.encoding,
        has_header=mapping.has_header,
        skip_rows=mapping.skip_rows,
        date_format=mapping.date_format,
        amount_format=mapping.amount_format,
        column_date=mapping.column_date,
        column_amount=mapping.column_amount,
        column_counterparty=mapping.column_counterparty,
        column_description=mapping.column_description,
        column_reference=mapping.column_reference,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


def build_account_suggestion_response(
    pattern: "AccountingPattern",
) -> "AccountSuggestionResponse":
    """Build AccountSuggestionResponse from ORM model."""
    from app.schemas.receipt import AccountSuggestionResponse

    return AccountSuggestionResponse(
        skr03_account_id=pattern.skr03_account_id,
        confidence=pattern.confidence,
        pattern=pattern.pattern,
    )


def build_export_log_response(log: "ExportLog") -> "ExportLogResponse":
    """Build ExportLogResponse from ORM model."""
    from app.schemas.datev import ExportLogResponse

    return ExportLogResponse(
        id=log.id,
        export_type=log.export_type,
        export_format=log.export_format,
        transaction_count=log.transaction_count,
        line_item_count=log.line_item_count,
        date_from=log.date_from,
        date_to=log.date_to,
        beraternummer=log.beraternummer,
        mandantennummer=log.mandantennummer,
        filename=log.filename,
        created_at=log.created_at.isoformat(),
    )


def build_oms_sync_log_response(log: "OmsSyncLog") -> "OmsSyncLogResponse":
    """Build OmsSyncLogResponse from ORM model."""
    from app.schemas.oms import OmsSyncLogResponse

    return OmsSyncLogResponse(
        id=log.id,
        start_date=log.start_date,
        end_date=log.end_date,
        fetched_count=log.fetched_count,
        imported_count=log.imported_count,
        skipped_count=log.skipped_count,
        status=log.status.value,
        error_message=log.error_message,
        created_at=log.created_at,
    )


def build_paypal_sync_log_response(log: "PayPalSyncLog") -> "PayPalSyncLogResponse":
    """Build PayPalSyncLogResponse from ORM model."""
    from app.schemas.paypal import PayPalSyncLogResponse

    return PayPalSyncLogResponse(
        id=log.id,
        start_date=log.start_date,
        end_date=log.end_date,
        fetched_count=log.fetched_count,
        imported_count=log.imported_count,
        fee_count=log.fee_count,
        status=log.status,
        error_message=log.error_message,
        created_at=log.created_at,
    )


def build_oms_store_response(store: "OmsStore") -> "OmsStoreResponse":
    """Build OmsStoreResponse from ORM model."""
    from app.schemas.oms import OmsStoreResponse

    return OmsStoreResponse(
        id=store.id,
        store_type=store.store_type,
        label=store.label,
        external_shop_id=store.external_shop_id,
        provider_id=store.provider_id,
        source_config_id=store.source_config_id,
        source_config_name=store.source_config.name if store.source_config else None,
        match_strategy=store.match_strategy,
        created_at=store.created_at,
        updated_at=store.updated_at,
    )


def build_oms_settings_response(
    has_credentials: bool,
    stores: Sequence["OmsStore"],
) -> "OmsSettingsResponse":
    """Build OmsSettingsResponse from credential flag and store list."""
    from app.schemas.oms import OmsSettingsResponse

    return OmsSettingsResponse(
        has_credentials=has_credentials,
        stores=[build_oms_store_response(store) for store in stores],
    )


def build_paypal_sync_response(result: "SyncResult") -> "PayPalSyncResponse":
    """Build PayPalSyncResponse from SyncResult."""
    from app.schemas.paypal import PayPalSyncResponse

    if result.sync_log_id is None:
        raise ValueError("PayPal SyncResult is missing sync_log_id; a PayPal sync must always create a sync log")

    return PayPalSyncResponse(
        imported_count=result.imported_count,
        skipped_count=result.skipped_count,
        fee_count=result.fee_count,
        sync_log_id=result.sync_log_id,
        errors=result.errors,
    )


def build_bulk_link_response(
    linked_count: int,
    skipped_count: int,
    receipt_open_amount: Decimal,
    amount_difference: Decimal,
) -> "BulkLinkResponse":
    """Build BulkLinkResponse with computed is_amount_matched."""
    from app.schemas.receipt import BulkLinkResponse

    return BulkLinkResponse(
        linked_count=linked_count,
        skipped_count=skipped_count,
        receipt_open_amount=receipt_open_amount,
        amount_difference=amount_difference,
        is_amount_matched=abs(amount_difference) <= Decimal("0.02"),
    )
