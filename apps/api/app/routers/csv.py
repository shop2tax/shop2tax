"""CSV upload and parsing router.

Provides endpoints for:
1. File-based upload (upload once, reference by file_id)
2. Generic CSV with user-defined column mapping (banks + marketplaces)
3. OMS enrichment for marketplace CSV rows
"""

import logging

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.rate_limit import RATE_LIMIT_CSV_UPLOAD, limiter
from app.database import get_db
from app.deps import CurrentUser, get_current_user
from app.schemas.csv import (
    CsvAnalyzeResponse,
    CsvEnrichResponse,
    CsvFileUploadResponse,
    EnrichedRowResponse,
    GenericCsvMappingRequest,
    GenericCsvParseResponse,
    MarketplaceCsvParseResponse,
    MarketplaceParsedRowResponse,
    ParsedRowResponse,
)
from app.services.csv_file_store import store_csv_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/csv", tags=["csv"])

# Maximum file size: 10 MB
MAX_FILE_SIZE = 10 * 1024 * 1024


async def resolve_csv_content(
    file_id: str | None,
    file: UploadFile | None,
) -> tuple[bytes, str] | tuple[None, str]:
    """Resolve CSV content from file_id or direct upload.

    Returns (content, filename) on success, or (None, error_message) on failure.
    """
    from app.services.csv_file_store import get_csv_file

    if file_id:
        stored = get_csv_file(file_id)
        if stored is None:
            return None, "File not found or expired. Please re-upload."
        return stored.content, stored.filename

    if file and file.filename:
        if not file.filename.lower().endswith((".csv", ".txt", ".tsv")):
            return None, "Only CSV, TXT, and TSV files are supported"
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            return None, f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB"
        if len(content) == 0:
            return None, "File is empty"
        return content, file.filename

    return None, "Either file or file_id is required"


class MappingAdapter:
    """Adapter to make request mapping work with parse_csv_with_mapping."""

    def __init__(self, request: GenericCsvMappingRequest):
        self.delimiter = request.delimiter
        self.encoding = request.encoding
        self.has_header = request.has_header
        self.skip_rows = request.skip_rows
        self.date_format = request.date_format
        # Annotated to match CsvMappingLike protocol (request narrows to str)
        self.amount_format: str | None = request.amount_format
        self.column_date = request.column_date
        self.column_amount = request.column_amount
        self.column_counterparty = request.column_counterparty
        self.column_description = request.column_description
        self.column_reference = request.column_reference
        self.column_filter = request.column_filter
        # Annotated to match CsvMappingLike protocol; set via Query() param after construction
        self.filter_include_values: list | None = None


@router.post("/upload-file", response_model=CsvFileUploadResponse)
@limiter.limit(RATE_LIMIT_CSV_UPLOAD)
async def upload_csv_file(
    request: Request,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
) -> CsvFileUploadResponse:
    """Upload a CSV file and get a file_id for follow-up requests.

    The file is stored temporarily (30 minutes). Use the returned file_id
    with /analyze, /parse-generic, and /enrich endpoints instead of
    re-uploading the file each time.
    """
    if not file.filename:
        return CsvFileUploadResponse(success=False, filename="unknown", error="No filename provided")

    if not file.filename.lower().endswith((".csv", ".txt", ".tsv")):
        return CsvFileUploadResponse(success=False, filename=file.filename, error="Only CSV, TXT, and TSV files are supported")

    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        return CsvFileUploadResponse(
            success=False,
            filename=file.filename,
            error=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB",
        )

    if len(content) == 0:
        return CsvFileUploadResponse(success=False, filename=file.filename, error="File is empty")

    stored = store_csv_file(file.filename, content)

    return CsvFileUploadResponse(
        success=True,
        file_id=stored.file_id,
        filename=stored.filename,
        expires_at=stored.expires_at,
    )


# --- Generic CSV Endpoints (for bank imports with column mapping) ---


@router.post("/analyze", response_model=CsvAnalyzeResponse)
@limiter.limit(RATE_LIMIT_CSV_UPLOAD)
async def analyze_csv(
    request: Request,
    file: UploadFile | None = File(None),
    file_id: str | None = Form(None),
    user: CurrentUser = Depends(get_current_user),
) -> CsvAnalyzeResponse:
    """Analyze a CSV file and return detected options + column information.

    Accepts either a file upload OR a file_id from /upload-file.

    Use this endpoint for CSVs that require user-defined column mapping.
    Returns auto-detected settings (editable in UI) and column headers with sample values.

    After analysis, use /csv/parse-generic with the mapping to parse the CSV.
    """
    from app.services.generic_csv_parser import DateAmbiguity, compute_unique_values, detect_csv_options

    result = await resolve_csv_content(file_id, file)
    if result[0] is None:
        return CsvAnalyzeResponse(success=False, filename="unknown", error=result[1])
    content, filename = result

    # Detect CSV options
    try:
        options = detect_csv_options(content)
    except Exception as exc:
        return CsvAnalyzeResponse(
            success=False,
            filename=filename,
            error=f"Analysis failed: {exc}",
        )

    # Build suggested columns from content analysis
    suggested = None
    if options.suggested_columns:
        from app.schemas.csv import SuggestedColumns as SuggestedColumnsSchema

        suggested = SuggestedColumnsSchema(
            column_date=options.suggested_columns.column_date,
            column_amount=options.suggested_columns.column_amount,
            column_counterparty=options.suggested_columns.column_counterparty,
            column_description=options.suggested_columns.column_description,
            column_reference=options.suggested_columns.column_reference,
        )

    # Compute ALL unique values per column (for filter dropdowns)
    # sample_values only has 5 rows — not enough for filtering
    unique_values = compute_unique_values(content, options)

    return CsvAnalyzeResponse(
        success=True,
        filename=filename,
        delimiter=options.delimiter,
        encoding=options.encoding,
        has_header=options.has_header,
        skip_rows=options.skip_rows,
        date_format=options.date_format,
        date_ambiguous=options.date_ambiguity == DateAmbiguity.AMBIGUOUS,
        amount_format=options.amount_format,
        column_headers=options.column_headers,
        sample_values=options.sample_values,
        unique_values=unique_values,
        suggested_columns=suggested,
    )


@router.post("/parse-generic", response_model=GenericCsvParseResponse)
@limiter.limit(RATE_LIMIT_CSV_UPLOAD)
async def parse_generic_csv(
    request: Request,
    file: UploadFile | None = File(None),
    file_id: str | None = Form(None),
    mapping: GenericCsvMappingRequest = Depends(),
    filter_include_values: list[str] | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
) -> GenericCsvParseResponse:
    """Parse a CSV file with user-provided column mapping.

    Accepts either a file upload OR a file_id from /upload-file.

    Use this endpoint after /csv/analyze to parse CSVs with custom mapping.
    Returns parsed rows for preview before import.

    The mapping parameter specifies:
    - CSV options (delimiter, encoding, skip_rows, etc.)
    - Column assignments (which columns map to date, amount, counterparty, etc.)
    """
    from app.services.generic_csv_parser import GenericCsvParseError, parse_csv_with_mapping

    result = await resolve_csv_content(file_id, file)
    if result[0] is None:
        return GenericCsvParseResponse(success=False, error=result[1])
    content, _filename = result

    # Create a temporary CsvMappingProfile-like object from request
    # We use a simple object instead of the ORM model since we don't need DB persistence here
    adapted_mapping = MappingAdapter(mapping)
    # Override filter_include_values from explicit Query param (Depends() can't parse list[str] from repeated query params)
    if filter_include_values is not None:
        adapted_mapping.filter_include_values = filter_include_values

    # Parse CSV with mapping
    try:
        result = parse_csv_with_mapping(content, adapted_mapping)
    except GenericCsvParseError as exc:
        return GenericCsvParseResponse(
            success=False,
            error=str(exc),
        )
    except Exception as exc:
        return GenericCsvParseResponse(
            success=False,
            error=f"Parse error: {exc}",
        )

    # Convert to response format

    rows = [
        ParsedRowResponse(
            date=row.date,
            amount=row.amount,
            counterparty=row.counterparty,
            description=row.description,
            source_reference=row.source_reference,
        )
        for row in result.rows
    ]

    return GenericCsvParseResponse(
        success=True,
        row_count=len(rows),
        rows=rows,
        errors=result.errors,
        filtered_count=result.filtered_count,
    )


# --- Marketplace CSV Parsing (Etsy, Amazon, Shopify) ---


@router.post("/parse-marketplace", response_model=MarketplaceCsvParseResponse)
@limiter.limit(RATE_LIMIT_CSV_UPLOAD)
async def parse_marketplace_csv(
    request: Request,
    source_config_id: str = Form(...),
    file: UploadFile | None = File(None),
    file_id: str | None = Form(None),
    oms_store_id: str | None = Form(None),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> MarketplaceCsvParseResponse:
    """Parse a marketplace CSV using a dedicated parser (skips analyze + column mapping).

    The source_config_id determines which parser to use (Etsy, Amazon, etc.).
    Returns enriched rows with transaction type detection and SKR03 assignment.

    If oms_store_id is provided, rows with order_ids are automatically enriched
    with OMS customer data (counterparty → customer name).

    Flow: upload-file → parse-marketplace → /transactions/import
    """
    from sqlalchemy import select

    from app.models.site_settings import SiteSettings
    from app.models.source import SourceType, TransactionSourceConfig
    from app.services.etsy_parser import EtsyParseError, EtsyStatementParser
    from app.services.shopify_parser import ShopifyParseError, ShopifyStatementParser

    resolved = await resolve_csv_content(file_id, file)
    if resolved[0] is None:
        return MarketplaceCsvParseResponse(success=False, error=resolved[1])
    content, _filename = resolved

    # Load source config to determine parser and tax settings
    source_config = database.scalar(select(TransactionSourceConfig).where(TransactionSourceConfig.id == source_config_id))
    if not source_config:
        return MarketplaceCsvParseResponse(success=False, error=f"Source config not found: {source_config_id}")

    if source_config.type != SourceType.MARKETPLACE_MAPPING:
        return MarketplaceCsvParseResponse(
            success=False,
            error=f"Source '{source_config.name}' is not a marketplace source (type: {source_config.type.value})",
        )

    # Load global tax settings
    site_settings = database.scalar(select(SiteSettings).where(SiteSettings.id == 1))
    is_kleinunternehmer = site_settings.is_small_business if site_settings and site_settings.is_small_business is not None else True

    # Extract marketplace-specific config
    config = source_config.source_config or {}
    has_ust_id: bool = config.get("has_ust_id_registered", True)

    # Dispatch to the correct marketplace parser via config.parser
    parser_type = config.get("parser", "").lower()
    if parser_type == "etsy":
        parser = EtsyStatementParser(
            is_kleinunternehmer=is_kleinunternehmer,
            has_ust_id=has_ust_id,
        )
        try:
            result = parser.parse(content, source_config_id)
        except EtsyParseError as exc:
            return MarketplaceCsvParseResponse(success=False, error=str(exc))
    elif parser_type == "shopify":
        shopify_parser = ShopifyStatementParser(
            is_kleinunternehmer=is_kleinunternehmer,
            has_ust_id=has_ust_id,
        )
        try:
            result = shopify_parser.parse(content, source_config_id)
        except ShopifyParseError as exc:
            return MarketplaceCsvParseResponse(success=False, error=str(exc))
    elif parser_type == "amazon":
        from app.services.amazon_parser import AmazonParseError, AmazonSettlementParser

        amazon_parser = AmazonSettlementParser(
            is_kleinunternehmer=is_kleinunternehmer,
            has_ust_id=has_ust_id,
        )
        try:
            result = amazon_parser.parse(content, source_config_id)
        except AmazonParseError as exc:
            return MarketplaceCsvParseResponse(success=False, error=str(exc))
    else:
        return MarketplaceCsvParseResponse(
            success=False,
            error=f"No marketplace parser available for '{source_config.name}' (parser: '{parser_type}'). Currently supported: Etsy, Shopify, Amazon.",
        )

    # OMS enrichment: enrich on mutable dataclasses BEFORE Pydantic conversion
    enrichment_stats = None
    if oms_store_id:
        enrichment_stats = await _enrich_marketplace_rows_with_oms(result.rows, oms_store_id, database)

    # Convert to response format (after enrichment so description/counterparty are updated)
    # Extract marketplace_type from the parser-specific type attribute
    def get_marketplace_type(row) -> str:
        # Synthetic fee rows have marketplace_type="fee" in extra_data (takes priority)
        if row.extra_data.get("marketplace_type") == "fee":
            return "fee"
        if hasattr(row, "etsy_type"):
            return row.etsy_type.value
        if hasattr(row, "shopify_type"):
            return row.shopify_type.value
        if hasattr(row, "amazon_type"):
            return row.amazon_type.value.lower()
        return row.extra_data.get("marketplace_type", "unknown")

    rows = [
        MarketplaceParsedRowResponse(
            date=row.date,
            amount=row.amount,
            counterparty=row.counterparty,
            description=row.description,
            source_reference=row.source_reference,
            marketplace_type=get_marketplace_type(row),
            suggested_skr03=row.suggested_skr03,
            order_id=row.order_id,
            oms_order_id=row.extra_data.get("oms_order_id"),
            is_internal_transfer=row.is_internal_transfer,
            is_rc_eligible=row.is_rc_eligible,
            rc_fee_amount=row.rc_fee_amount,
            import_hash=row.import_hash,
            extra_data=row.extra_data,
        )
        for row in result.rows
    ]

    # Compute RC USt from parser-provided rc_fee_amount (when USt-ID registered)
    from decimal import Decimal

    from app.core.constants import DEFAULT_RC_TAX_RATE

    rc_ust_amount: Decimal | None = None
    if has_ust_id:
        # Use rc_fee_amount from parser (Etsy: abs(amount) for fee rows, Shopify: Fee column)
        rc_fee_total = sum(row.rc_fee_amount or Decimal("0") for row in rows if row.is_rc_eligible)
        if rc_fee_total > 0:
            rc_rate = site_settings.rc_tax_rate if site_settings else DEFAULT_RC_TAX_RATE
            rc_ust_amount = round(rc_fee_total * rc_rate, 2)

    return MarketplaceCsvParseResponse(
        success=True,
        row_count=len(rows),
        rows=rows,
        errors=result.errors,
        skipped_rows=result.skipped_rows,
        enrichment=enrichment_stats,
        rc_ust_amount=rc_ust_amount,
    )


async def _enrich_marketplace_rows_with_oms(
    rows: list,
    oms_store_id: str,
    database: Session,
) -> dict:
    """Enrich marketplace-parsed rows that have order_ids with OMS customer data.

    Modifies rows in-place (counterparty → customer name for sales rows).
    Returns enrichment statistics.
    """
    from datetime import datetime as dt
    from datetime import timedelta

    from sqlalchemy import select

    from app.models.oms_store import OmsStore
    from app.services.oms_matching import build_order_lookup, match_transaction_to_order
    from app.services.oms_provider import get_default_oms_provider

    provider = get_default_oms_provider(database)
    if provider is None:
        return {"matched": 0, "unmatched": 0, "skipped": 0, "error": "Warenwirtschaft nicht konfiguriert"}

    store = database.scalar(select(OmsStore).where(OmsStore.id == oms_store_id))
    if store is None:
        return {"matched": 0, "unmatched": 0, "skipped": 0, "error": "Store nicht gefunden"}

    # Only enrich rows with order_ids (sales rows)
    rows_with_orders = [r for r in rows if r.order_id]
    rows_without_orders = len(rows) - len(rows_with_orders)

    if not rows_with_orders:
        return {"matched": 0, "unmatched": 0, "skipped": rows_without_orders}

    # Scope OMS API query to CSV date range
    # Default: 3 days lookback. Amazon settlements include orders from weeks
    # before the settlement date, so use 45 days lookback.
    is_amazon = any(getattr(r, "amazon_type", None) is not None for r in rows_with_orders)
    lookback_days = 45 if is_amazon else 3
    row_dates = [r.date for r in rows_with_orders]
    min_order_date = dt.combine(min(row_dates) - timedelta(days=lookback_days), dt.min.time())
    max_order_date = dt.combine(max(row_dates) + timedelta(days=1), dt.max.time())

    try:
        orders, _is_cached, _expires_at = await provider.fetch_orders_cached(
            store_ids=[store.external_shop_id],
            min_date=min_order_date,
            max_date=max_order_date,
        )
    except Exception as exc:
        logger.error(f"OMS API error during marketplace enrichment: {exc}")
        return {"matched": 0, "unmatched": len(rows_with_orders), "skipped": rows_without_orders, "error": str(exc)}

    # Build order lookup by order number
    order_number_lookup, email_lookup = build_order_lookup(orders)

    matched = 0
    unmatched = 0
    for row in rows_with_orders:
        matched_order = match_transaction_to_order(
            order_number_lookup=order_number_lookup,
            email_lookup=email_lookup,
            match_strategy=store.match_strategy,
            source_reference=row.order_id,
            counterparty=row.counterparty,
        )
        if matched_order:
            row.extra_data["oms_order_id"] = matched_order.order_id
            enrichment = provider.enrich_transaction(matched_order)
            if enrichment.customer_name:
                row.counterparty = enrichment.customer_name
            # Update description for revenue rows (Etsy: sale/refund, Shopify: charge/refund, Amazon: Order/Refund)
            marketplace_type_value = ""
            if hasattr(row, "etsy_type"):
                marketplace_type_value = row.etsy_type.value
            elif hasattr(row, "shopify_type"):
                marketplace_type_value = row.shopify_type.value
            elif hasattr(row, "amazon_type"):
                marketplace_type_value = row.amazon_type.value
            if enrichment.invoice_number and marketplace_type_value in ("sale", "refund", "charge", "Order", "Refund"):
                row.description = enrichment.invoice_number
            matched += 1
        else:
            unmatched += 1

    return {"matched": matched, "unmatched": unmatched, "skipped": rows_without_orders}


# --- OMS Enrichment ---


@router.post("/enrich", response_model=CsvEnrichResponse)
@limiter.limit(RATE_LIMIT_CSV_UPLOAD)
async def enrich_csv(
    request: Request,
    file_id: str = Form(...),
    oms_store_id: str = Form(...),
    mapping: GenericCsvMappingRequest = Depends(),
    filter_include_values: list[str] | None = Query(None),
    offset: int = Form(0),
    limit: int = Form(100),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> CsvEnrichResponse:
    """Parse CSV and enrich rows with OMS order data.

    Reads the CSV via file_id, parses with mapping, fetches OMS orders
    for the linked store, and matches each row against orders.

    Returns enriched rows with customer name and invoice number from the OMS.
    """

    import time

    from sqlalchemy import select

    from app.models.oms_store import OmsStore
    from app.services.csv_file_store import get_csv_file
    from app.services.generic_csv_parser import GenericCsvParseError, parse_csv_with_mapping
    from app.services.oms_matching import build_order_lookup, match_transaction_to_order
    from app.services.oms_provider import get_default_oms_provider

    t_start = time.monotonic()
    timing: dict[str, float] = {}

    # 1. Resolve file
    stored = get_csv_file(file_id)
    if stored is None:
        return CsvEnrichResponse(success=False, error="File not found or expired. Please re-upload.")

    timing["resolve_file"] = round(time.monotonic() - t_start, 3)

    # 2. Look up OMS store
    t_step = time.monotonic()
    store = database.scalar(select(OmsStore).where(OmsStore.id == oms_store_id))
    if store is None:
        return CsvEnrichResponse(success=False, error="Store nicht gefunden.")

    timing["lookup_store"] = round(time.monotonic() - t_step, 3)

    # 3. Parse CSV with mapping
    adapted = MappingAdapter(mapping)
    # Override filter_include_values from explicit Query param (Depends() can't parse list[str] from repeated query params)
    if filter_include_values is not None:
        adapted.filter_include_values = filter_include_values

    t_step = time.monotonic()
    try:
        result = parse_csv_with_mapping(stored.content, adapted)
    except GenericCsvParseError as exc:
        return CsvEnrichResponse(success=False, error=str(exc))

    timing["parse_csv"] = round(time.monotonic() - t_step, 3)

    if not result.rows:
        return CsvEnrichResponse(success=True, total_rows=0)

    # 5. Fetch OMS orders for this store (scoped to CSV date range)
    provider = get_default_oms_provider(database)
    if provider is None:
        # No OMS provider configured — return rows without enrichment
        enriched_rows = [
            EnrichedRowResponse(
                date=row.date,
                amount=row.amount,
                counterparty=row.counterparty,
                description=row.description,
                source_reference=row.source_reference,
                match_status="no_enrichment",
            )
            for row in result.rows[offset : offset + limit]
        ]
        return CsvEnrichResponse(
            success=True,
            rows=enriched_rows,
            total_rows=len(result.rows),
            error="Warenwirtschaft nicht konfiguriert.",
        )

    # Extract date range from CSV rows to scope the OMS API query.
    # Without this, the API fetches ALL orders (20k+) instead of just the relevant ones.
    from datetime import datetime as dt
    from datetime import timedelta

    row_dates = [row.date for row in result.rows if row.date]
    min_order_date = None
    max_order_date = None
    if row_dates:
        min_order_date = dt.combine(min(row_dates) - timedelta(days=3), dt.min.time())
        max_order_date = dt.combine(max(row_dates) + timedelta(days=1), dt.max.time())

    # Use cached orders to avoid redundant API calls for repeated enrich requests
    t_step = time.monotonic()
    try:
        orders, is_cached, _expires_at = await provider.fetch_orders_cached(
            store_ids=[store.external_shop_id],
            min_date=min_order_date,
            max_date=max_order_date,
        )
    except Exception as exc:
        logger.error(f"OMS API error: {exc}")
        return CsvEnrichResponse(success=False, error=f"OMS API error: {exc}")

    timing["oms_fetch"] = round(time.monotonic() - t_step, 3)
    timing["oms_orders"] = len(orders)
    timing["oms_cached"] = 1.0 if is_cached else 0.0

    # 6. Build lookup and match
    order_number_lookup, email_lookup = build_order_lookup(orders)

    matched_count = 0
    unmatched_count = 0
    enriched_rows: list[EnrichedRowResponse] = []

    # Apply pagination to rows
    page_rows = result.rows[offset : offset + limit]

    t_step = time.monotonic()
    for row in page_rows:
        # Try source_reference first, then fall back to description (Etsy puts order numbers there)
        matched_order = match_transaction_to_order(
            order_number_lookup=order_number_lookup,
            email_lookup=email_lookup,
            match_strategy=store.match_strategy,
            source_reference=row.source_reference,
            counterparty=row.counterparty,
        )
        if not matched_order and row.description:
            matched_order = match_transaction_to_order(
                order_number_lookup=order_number_lookup,
                email_lookup=email_lookup,
                match_strategy=store.match_strategy,
                source_reference=row.description,
                counterparty=row.counterparty,
            )

        if matched_order:
            enrichment = provider.enrich_transaction(matched_order)
            enriched_rows.append(
                EnrichedRowResponse(
                    date=row.date,
                    amount=row.amount,
                    counterparty=row.counterparty,
                    description=row.description,
                    source_reference=row.source_reference,
                    enriched_counterparty=enrichment.customer_name,
                    enriched_description=enrichment.invoice_number,
                    enriched_date=enrichment.order_date,
                    enriched_amount=matched_order.total_cost,
                    match_status="matched",
                )
            )
            matched_count += 1
        else:
            enriched_rows.append(
                EnrichedRowResponse(
                    date=row.date,
                    amount=row.amount,
                    counterparty=row.counterparty,
                    description=row.description,
                    source_reference=row.source_reference,
                    match_status="unmatched",
                )
            )
            unmatched_count += 1

    timing["matching"] = round(time.monotonic() - t_step, 3)
    timing["total"] = round(time.monotonic() - t_start, 3)

    return CsvEnrichResponse(
        success=True,
        rows=enriched_rows,
        total_rows=len(result.rows),
        matched_count=matched_count,
        unmatched_count=unmatched_count,
        errors=result.errors,
        timing=timing,
    )
