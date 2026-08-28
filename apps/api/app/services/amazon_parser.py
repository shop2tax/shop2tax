"""Amazon Settlement Report Parser — dedicated parser for Amazon Flat File V2 exports.

This parser understands the Amazon Settlement Report V2 format and automatically:
1. Detects encoding (UTF-8 with BOM, Windows-1252, etc.)
2. Handles tab-delimited format (.txt files)
3. Parses German number formats (17,95 = 17.95 EUR)
4. Aggregates multiple CSV rows per order into Sale + Fee output rows
5. Handles 4 transaction types (Order, Refund, Transfer, Adjustment)
6. Assigns correct SKR03 accounts (no Reverse Charge — Amazon DE is domestic)

Settlement Report V2 columns (24):
settlement-id, settlement-start-date, settlement-end-date, deposit-date, total-amount,
currency, transaction-type, order-id, merchant-order-id, adjustment-id, shipment-id,
marketplace-name, amount-type, amount-description, amount, fulfillment-id, posted-date,
posted-date-time, order-item-code, merchant-order-item-id, merchant-adjustment-item-id,
sku, quantity-purchased, promotion-id
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from io import StringIO

from app.services.csv_utils import (
    compute_import_hash,
    parse_localized_date,
    parse_money,
    sniff_delimiter,
    sniff_encoding,
)

logger = logging.getLogger(__name__)

# --- Constants ---

# Expected Amazon Settlement V2 columns (lowercase normalized)
COL_SETTLEMENT_ID = "settlement-id"
COL_SETTLEMENT_START = "settlement-start-date"
COL_SETTLEMENT_END = "settlement-end-date"
COL_DEPOSIT_DATE = "deposit-date"
COL_TOTAL_AMOUNT = "total-amount"
COL_CURRENCY = "currency"
COL_TRANSACTION_TYPE = "transaction-type"
COL_ORDER_ID = "order-id"
COL_MERCHANT_ORDER_ID = "merchant-order-id"
COL_ADJUSTMENT_ID = "adjustment-id"
COL_SHIPMENT_ID = "shipment-id"
COL_MARKETPLACE = "marketplace-name"
COL_AMOUNT_TYPE = "amount-type"
COL_AMOUNT_DESCRIPTION = "amount-description"
COL_AMOUNT = "amount"
COL_FULFILLMENT_ID = "fulfillment-id"
COL_POSTED_DATE = "posted-date"
COL_POSTED_DATE_TIME = "posted-date-time"
COL_ORDER_ITEM_CODE = "order-item-code"
COL_SKU = "sku"
COL_QUANTITY = "quantity-purchased"
COL_PROMOTION_ID = "promotion-id"

REQUIRED_COLUMNS = [
    COL_SETTLEMENT_ID,
    COL_TRANSACTION_TYPE,
    COL_AMOUNT_TYPE,
    COL_AMOUNT,
]


class AmazonTransactionType(str, Enum):
    """Amazon transaction types from Settlement Report V2.

    Identified from transaction-type column. Used to determine:
    - SKR03 account assignment
    - Aggregation grouping
    - Description formatting
    """

    ORDER = "Order"
    REFUND = "Refund"
    TRANSFER = "Transfer"
    ADJUSTMENT = "Adjustment"

    def is_revenue(self) -> bool:
        """Returns True if this type represents revenue (order or refund)."""
        return self in {AmazonTransactionType.ORDER, AmazonTransactionType.REFUND}

    def is_fee(self) -> bool:
        """Returns True if this represents a fee row (standalone, no order-id)."""
        # Fees are determined by amount-type = ItemFees, not transaction-type
        return False

    def is_rc_eligible(self) -> bool:
        """Returns False — Amazon DE charges 19% German VAT, no Reverse Charge.

        Amazon EU S.à r.l. Niederlassung Deutschland (DE814584193) is a domestic
        German entity. Unlike Etsy Ireland or Shopify Ireland, there is no
        intra-EU B2B service that would trigger §13b Reverse Charge.
        """
        return False

    def suggested_skr03_account(
        self,
        is_kleinunternehmer: bool,
    ) -> int:
        """Returns suggested SKR03 account for revenue.

        Args:
            is_kleinunternehmer: True if seller is Kleinunternehmer §19 UStG

        Returns:
            SKR03 account number
        """
        # Revenue accounts
        if self in {AmazonTransactionType.ORDER, AmazonTransactionType.REFUND}:
            return 8195 if is_kleinunternehmer else 8400

        # Transfer — Geldtransit (internal transfer)
        if self == AmazonTransactionType.TRANSFER:
            return 1360

        # Adjustment — sonstige betriebliche Aufwendungen
        if self == AmazonTransactionType.ADJUSTMENT:
            return 4900

        message = f"No SKR03 account for type {self.value}"
        raise ValueError(message)

    def format_description(self, order_id: str | None, amount_description: str | None) -> str:
        """Format transaction description based on type."""
        type_labels = {
            AmazonTransactionType.ORDER: "Amazon Verkauf",
            AmazonTransactionType.REFUND: "Amazon Rückerstattung",
            AmazonTransactionType.TRANSFER: "Amazon Auszahlung",
            AmazonTransactionType.ADJUSTMENT: "Amazon Anpassung",
        }

        label = type_labels.get(self, "Amazon Transaktion")

        if order_id:
            return f"{label} #{order_id}"
        if amount_description:
            return f"{label}: {amount_description[:50]}"
        return label


class AmazonAmountType(str, Enum):
    """Amazon amount types from amount-type column.

    Determines whether an amount row is revenue, fee, or promotion.
    """

    ITEM_PRICE = "ItemPrice"
    ITEM_FEES = "ItemFees"
    PROMOTION = "Promotion"
    OTHER = "other"

    @classmethod
    def from_string(cls, value: str) -> AmazonAmountType:
        """Parse amount-type string to enum value."""
        normalized = value.strip()
        for member in cls:
            if member.value.lower() == normalized.lower():
                return member
        return cls.OTHER


@dataclass(slots=True)
class AmazonParsedRow:
    """A parsed Amazon Settlement row ready for Transaction creation.

    This represents an aggregated output row (multiple CSV rows → one AmazonParsedRow).
    """

    date: date
    amount: Decimal
    counterparty: str
    description: str
    source_reference: str | None = None
    amazon_type: AmazonTransactionType = AmazonTransactionType.ORDER
    amount_type: AmazonAmountType = AmazonAmountType.ITEM_PRICE
    suggested_skr03: int = 4900
    order_id: str | None = None
    is_internal_transfer: bool = False
    is_rc_eligible: bool = False  # Always False for Amazon DE
    rc_fee_amount: Decimal = field(default_factory=lambda: Decimal("0"))  # Always 0 — Amazon DE is domestic
    import_hash: str | None = None
    extra_data: dict = field(default_factory=dict)


@dataclass(slots=True)
class AmazonParseResult:
    """Result of parsing an Amazon Settlement Report."""

    rows: list[AmazonParsedRow]
    errors: list[str]
    total_rows: int = 0
    skipped_rows: int = 0
    settlement_id: str | None = None
    settlement_start: date | None = None
    settlement_end: date | None = None
    deposit_date: date | None = None


class AmazonParseError(Exception):
    """Raised when Amazon Settlement parsing fails."""

    pass


# --- Helper Functions ---


def normalize_headers(headers: list[str]) -> dict[str, int]:
    """Normalize headers to lowercase and map to column indices.

    Returns: {normalized_name: column_index}
    """
    return {header.strip().lower(): index for index, header in enumerate(headers)}


def is_settlement_summary_row(row: dict[str, str]) -> bool:
    """Detect Settlement Summary row semantically.

    Settlement Summary rows have:
    - transaction-type: empty
    - total-amount: filled (non-empty)
    - order-id: empty

    These rows contain aggregate data, not individual transactions.
    """
    transaction_type = row.get(COL_TRANSACTION_TYPE, "").strip()
    total_amount = row.get(COL_TOTAL_AMOUNT, "").strip()
    order_id = row.get(COL_ORDER_ID, "").strip()

    return bool(not transaction_type and total_amount and not order_id)


def compute_amazon_import_hash(
    source_config_id: str,
    transaction_date: date,
    amazon_type: AmazonTransactionType,
    amount: Decimal,
    order_id: str | None,
    row_type: str,  # "sale", "fee", "payout", "adjustment"
) -> str:
    """Compute SHA-256 hash for duplicate detection.

    Includes row_type to differentiate Sale vs Fee rows for the same order.
    """
    return compute_import_hash(
        source_config_id,
        transaction_date.isoformat(),
        amazon_type.value,
        str(amount.quantize(Decimal("0.01"))),
        order_id or "",
        row_type,
    )


# --- Aggregation Key ---


@dataclass(frozen=True)
class AggregationKey:
    """Key for grouping CSV rows into aggregated transactions.

    Groups by (order-id, transaction-type) for order-related rows,
    or (settlement-id, posted-date, amount-description) for non-order fees.
    """

    order_id: str | None
    transaction_type: str
    settlement_id: str | None = None
    posted_date: str | None = None
    amount_description: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, str]) -> AggregationKey:
        """Create aggregation key from a CSV row."""
        order_id = row.get(COL_ORDER_ID, "").strip() or None
        transaction_type = row.get(COL_TRANSACTION_TYPE, "").strip()

        if order_id:
            # Order-related row: group by (order-id, transaction-type)
            return cls(order_id=order_id, transaction_type=transaction_type)

        # Non-order row (standalone fees): group by settlement + date + description
        return cls(
            order_id=None,
            transaction_type=transaction_type,
            settlement_id=row.get(COL_SETTLEMENT_ID, "").strip() or None,
            posted_date=row.get(COL_POSTED_DATE, "").strip() or None,
            amount_description=row.get(COL_AMOUNT_DESCRIPTION, "").strip() or None,
        )


# --- Main Parser Class ---


class AmazonSettlementParser:
    """Parser for Amazon Settlement Report V2 (Flat File) exports.

    Usage:
        parser = AmazonSettlementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(raw_bytes, source_config_id)
        for row in result.rows:
            print(row.amazon_type, row.amount, row.suggested_skr03)

    Note:
        The has_ust_id parameter is accepted for interface parity with
        EtsyStatementParser and ShopifyTransactionParser, but has no effect.
        Amazon EU S.à r.l. Niederlassung Deutschland charges 19% German VAT
        on all fees — there is no §13b Reverse Charge scenario.
    """

    def __init__(
        self,
        is_kleinunternehmer: bool = True,
        has_ust_id: bool = True,  # No effect — Amazon DE is domestic
    ):
        """Initialize parser with tax scenario configuration.

        Args:
            is_kleinunternehmer: True if seller is Kleinunternehmer §19 UStG
            has_ust_id: Accepted for interface parity but has no effect.
                Amazon DE charges German VAT, no Reverse Charge applies.
        """
        self.is_kleinunternehmer = is_kleinunternehmer
        self.has_ust_id = has_ust_id  # Stored but unused

    def parse(self, raw_bytes: bytes, source_config_id: str) -> AmazonParseResult:
        """Parse raw CSV/TXT bytes into AmazonParsedRow list.

        Args:
            raw_bytes: Raw Settlement Report file content
            source_config_id: UUID of the TransactionSourceConfig

        Returns:
            AmazonParseResult with aggregated rows and any errors

        Raises:
            AmazonParseError: If file format is invalid or currency is not EUR
        """
        import csv

        # Step 1: Detect encoding
        encoding = sniff_encoding(raw_bytes)

        # Step 2: Decode content
        try:
            text_content = raw_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            text_content = raw_bytes.decode("utf-8", errors="replace")

        # Step 3: Detect delimiter (typically tab for Amazon)
        first_line = text_content.split("\n")[0] if "\n" in text_content else text_content
        delimiter = sniff_delimiter(first_line)

        # Step 4: Parse CSV
        try:
            reader = csv.reader(StringIO(text_content), delimiter=delimiter)
            rows_list = list(reader)
        except csv.Error:
            reader = csv.reader(StringIO(text_content), delimiter=delimiter, quoting=csv.QUOTE_NONE)
            rows_list = list(reader)

        if not rows_list:
            raise AmazonParseError("Empty file")

        # Step 5: Find header row and build column map
        headers = rows_list[0]
        column_map = normalize_headers(headers)

        # Validate required columns exist
        missing = [col for col in REQUIRED_COLUMNS if col not in column_map]
        if missing:
            raise AmazonParseError(f"Missing required columns: {missing}. Found: {list(column_map.keys())}")

        # Step 6: Parse data rows into dicts and validate currency
        raw_rows: list[dict[str, str]] = []
        errors: list[str] = []
        total_rows = 0
        skipped_rows = 0
        settlement_id = None
        settlement_start = None
        settlement_end = None
        deposit_date = None

        for row_index, row in enumerate(rows_list[1:], start=2):
            if not row or all(not cell.strip() for cell in row):
                skipped_rows += 1
                continue

            total_rows += 1

            # Convert row to dict using column map
            row_dict = {}
            for col_name, col_index in column_map.items():
                if col_index < len(row):
                    row_dict[col_name] = row[col_index].strip()
                else:
                    row_dict[col_name] = ""

            # Extract settlement metadata from first data row
            if settlement_id is None:
                settlement_id = row_dict.get(COL_SETTLEMENT_ID, "").strip() or None
                start_str = row_dict.get(COL_SETTLEMENT_START, "").strip()
                end_str = row_dict.get(COL_SETTLEMENT_END, "").strip()
                deposit_str = row_dict.get(COL_DEPOSIT_DATE, "").strip()

                try:
                    settlement_start = parse_localized_date(start_str) if start_str else None
                    settlement_end = parse_localized_date(end_str) if end_str else None
                    deposit_date = parse_localized_date(deposit_str) if deposit_str else None
                except ValueError:
                    pass  # Dates are optional metadata

            # Validate currency (EUR only)
            currency = row_dict.get(COL_CURRENCY, "").strip().upper()
            if currency and currency != "EUR":
                raise AmazonParseError(
                    f"Unsupported currency: {currency}. Only EUR settlements are supported. "
                    f"Row {row_index}: order-id={row_dict.get(COL_ORDER_ID, '')}"
                )

            # Skip Settlement Summary rows (metadata only)
            if is_settlement_summary_row(row_dict):
                skipped_rows += 1
                continue

            raw_rows.append(row_dict)

        # Step 7: Aggregate rows by (order-id, transaction-type)
        parsed_rows = self._aggregate_rows(raw_rows, source_config_id, errors)

        return AmazonParseResult(
            rows=parsed_rows,
            errors=errors,
            total_rows=total_rows,
            skipped_rows=skipped_rows,
            settlement_id=settlement_id,
            settlement_start=settlement_start,
            settlement_end=settlement_end,
            deposit_date=deposit_date,
        )

    def _aggregate_rows(
        self,
        raw_rows: list[dict[str, str]],
        source_config_id: str,
        errors: list[str],
    ) -> list[AmazonParsedRow]:
        """Aggregate raw CSV rows into Sale/Fee/Payout output rows.

        Aggregation Strategy:
        - Group by (order-id, transaction-type) for orders
        - Group by (settlement-id, posted-date, amount-description) for non-order fees
        - ItemPrice amounts → Sale Row (including negative Promotion amounts)
        - ItemFees amounts → Fee Row
        - Transfer → Payout Row
        """
        # Group rows by aggregation key
        groups: dict[AggregationKey, list[dict[str, str]]] = defaultdict(list)
        for row in raw_rows:
            key = AggregationKey.from_row(row)
            groups[key].append(row)

        parsed_rows: list[AmazonParsedRow] = []

        for key, group_rows in groups.items():
            try:
                rows_for_key = self._process_group(key, group_rows, source_config_id)
                parsed_rows.extend(rows_for_key)
            except Exception as exc:
                order_info = f"order={key.order_id}" if key.order_id else f"desc={key.amount_description}"
                errors.append(f"Group {key.transaction_type} ({order_info}): {exc}")
                logger.debug(f"Failed to process group: {exc}", exc_info=True)

        return parsed_rows

    def _process_group(
        self,
        key: AggregationKey,
        rows: list[dict[str, str]],
        source_config_id: str,
    ) -> list[AmazonParsedRow]:
        """Process a group of rows with the same aggregation key.

        Returns 0-2 rows: Sale/Refund/Payout + Fee (if fees exist).
        """
        if not rows:
            return []

        # Determine transaction type
        transaction_type_str = key.transaction_type
        if not transaction_type_str:
            # Non-order fee without transaction type
            return self._process_standalone_fee(key, rows, source_config_id)

        try:
            amazon_type = AmazonTransactionType(transaction_type_str)
        except ValueError:
            logger.warning(f"Unknown transaction type: {transaction_type_str}")
            return []

        # Transfer (Payout) → single payout row
        if amazon_type == AmazonTransactionType.TRANSFER:
            return self._process_payout(key, rows, source_config_id)

        # Order or Refund → Sale Row + Fee Row
        return self._process_order(key, rows, amazon_type, source_config_id)

    def _process_order(
        self,
        key: AggregationKey,
        rows: list[dict[str, str]],
        amazon_type: AmazonTransactionType,
        source_config_id: str,
    ) -> list[AmazonParsedRow]:
        """Process Order or Refund group → Sale Row + Fee Row."""
        result: list[AmazonParsedRow] = []

        # Aggregate amounts by type
        item_price_total = Decimal("0")
        item_fees_total = Decimal("0")
        promotion_total = Decimal("0")
        first_row = rows[0]
        posted_date_str = first_row.get(COL_POSTED_DATE, "").strip()

        # Parse date from first row
        try:
            transaction_date = parse_localized_date(posted_date_str) if posted_date_str else date.today()
        except ValueError:
            transaction_date = date.today()

        for row in rows:
            amount_type_str = row.get(COL_AMOUNT_TYPE, "").strip()
            amount_str = row.get(COL_AMOUNT, "").strip()

            if not amount_str:
                continue

            amount = parse_money(amount_str)
            amount_type = AmazonAmountType.from_string(amount_type_str)

            if amount_type == AmazonAmountType.ITEM_PRICE:
                item_price_total += amount
            elif amount_type == AmazonAmountType.ITEM_FEES:
                item_fees_total += amount
            elif amount_type == AmazonAmountType.PROMOTION:
                promotion_total += amount  # Promotions are already negative

        # Sale Row: ItemPrice + Promotion
        sale_amount = item_price_total + promotion_total
        if sale_amount != Decimal("0"):
            sale_row = AmazonParsedRow(
                date=transaction_date,
                amount=sale_amount,
                counterparty="Amazon Kunde",
                description=amazon_type.format_description(key.order_id, None),
                source_reference=f"Order #{key.order_id}" if key.order_id else None,
                amazon_type=amazon_type,
                amount_type=AmazonAmountType.ITEM_PRICE,
                suggested_skr03=amazon_type.suggested_skr03_account(self.is_kleinunternehmer),
                order_id=key.order_id,
                is_internal_transfer=False,
                is_rc_eligible=False,
                import_hash=compute_amazon_import_hash(
                    source_config_id,
                    transaction_date,
                    amazon_type,
                    sale_amount,
                    key.order_id,
                    "sale",
                ),
                extra_data={
                    "marketplace": "amazon",
                    "marketplace_type": amazon_type.value.lower(),
                    "marketplace_category": "revenue",
                    "order_id": key.order_id,
                },
            )
            result.append(sale_row)

        # Fee Row: ItemFees
        if item_fees_total != Decimal("0"):
            fee_row = AmazonParsedRow(
                date=transaction_date,
                amount=item_fees_total,  # Fees are negative in CSV
                counterparty="Amazon EU S.à r.l. Niederlassung Deutschland",
                description=f"Amazon Gebühren #{key.order_id}" if key.order_id else "Amazon Gebühren",
                source_reference=f"Order #{key.order_id}_FEE" if key.order_id else None,
                amazon_type=amazon_type,
                amount_type=AmazonAmountType.ITEM_FEES,
                suggested_skr03=4761,  # Amazon Verkaufsgebühren (brutto inkl. 19% USt)
                order_id=key.order_id,
                is_internal_transfer=False,
                is_rc_eligible=False,
                import_hash=compute_amazon_import_hash(
                    source_config_id,
                    transaction_date,
                    amazon_type,
                    item_fees_total,
                    key.order_id,
                    "fee",
                ),
                extra_data={
                    "marketplace": "amazon",
                    "marketplace_type": "fee",
                    "marketplace_category": "fee",
                    "order_id": key.order_id,
                },
            )
            result.append(fee_row)

        return result

    def _process_payout(
        self,
        key: AggregationKey,
        rows: list[dict[str, str]],
        source_config_id: str,
    ) -> list[AmazonParsedRow]:
        """Process Transfer (Payout) group → single Payout Row."""
        total_amount = Decimal("0")
        first_row = rows[0]
        posted_date_str = first_row.get(COL_POSTED_DATE, "").strip()
        deposit_date_str = first_row.get(COL_DEPOSIT_DATE, "").strip()

        # Prefer deposit date for payouts
        try:
            transaction_date = parse_localized_date(deposit_date_str or posted_date_str)
        except ValueError:
            transaction_date = date.today()

        for row in rows:
            amount_str = row.get(COL_AMOUNT, "").strip()
            if amount_str:
                total_amount += parse_money(amount_str)

        if total_amount == Decimal("0"):
            return []

        settlement_id = first_row.get(COL_SETTLEMENT_ID, "").strip()

        return [
            AmazonParsedRow(
                date=transaction_date,
                amount=total_amount,
                counterparty="Amazon Auszahlung",
                description=AmazonTransactionType.TRANSFER.format_description(None, None),
                source_reference=f"Payout_{transaction_date.isoformat()}",
                amazon_type=AmazonTransactionType.TRANSFER,
                amount_type=AmazonAmountType.OTHER,
                suggested_skr03=1360,  # Geldtransit
                order_id=None,
                is_internal_transfer=True,
                is_rc_eligible=False,
                import_hash=compute_amazon_import_hash(
                    source_config_id,
                    transaction_date,
                    AmazonTransactionType.TRANSFER,
                    total_amount,
                    settlement_id,
                    "payout",
                ),
                extra_data={
                    "marketplace": "amazon",
                    "marketplace_type": "transfer",
                    "marketplace_category": "transfer",
                    "settlement_id": settlement_id,
                },
            )
        ]

    def _process_standalone_fee(
        self,
        key: AggregationKey,
        rows: list[dict[str, str]],
        source_config_id: str,
    ) -> list[AmazonParsedRow]:
        """Process non-order fees (Storage, Subscriptions, Advertising).

        These are fees without an order-id — standalone expense rows.
        """
        total_amount = Decimal("0")
        first_row = rows[0]
        posted_date_str = first_row.get(COL_POSTED_DATE, "").strip()
        amount_description = key.amount_description or "Sonstige Gebühr"

        try:
            transaction_date = parse_localized_date(posted_date_str) if posted_date_str else date.today()
        except ValueError:
            transaction_date = date.today()

        for row in rows:
            amount_str = row.get(COL_AMOUNT, "").strip()
            if amount_str:
                total_amount += parse_money(amount_str)

        if total_amount == Decimal("0"):
            return []

        settlement_id = key.settlement_id or ""

        return [
            AmazonParsedRow(
                date=transaction_date,
                amount=total_amount,
                counterparty="Amazon EU S.à r.l. Niederlassung Deutschland",
                description=f"Amazon {amount_description}",
                source_reference=f"Fee_{settlement_id}_{transaction_date.isoformat()}_{amount_description[:20]}",
                amazon_type=AmazonTransactionType.ADJUSTMENT,
                amount_type=AmazonAmountType.ITEM_FEES,
                suggested_skr03=4761,  # Amazon Verkaufsgebühren (brutto)
                order_id=None,
                is_internal_transfer=False,
                is_rc_eligible=False,
                import_hash=compute_amazon_import_hash(
                    source_config_id,
                    transaction_date,
                    AmazonTransactionType.ADJUSTMENT,
                    total_amount,
                    f"{settlement_id}_{amount_description}",
                    "standalone_fee",
                ),
                extra_data={
                    "marketplace": "amazon",
                    "marketplace_type": "fee",
                    "marketplace_category": "fee",
                    "amount_description": amount_description,
                    "settlement_id": settlement_id,
                },
            )
        ]
