"""Shopify Payment Transactions Parser — dedicated CSV parser for Shopify Payments exports.

This parser understands the Shopify Payment Transactions CSV format and automatically:
1. Detects encoding (UTF-8 with BOM, Windows-1252, etc.)
2. Detects delimiter (comma vs semicolon)
3. Parses timezone-aware datetime formats (2026-01-19 12:07:45 +0100)
4. Categorizes 6 transaction types to correct SKR03 accounts
5. Handles 4 tax scenarios (Kleinunternehmer × USt-ID registration)
6. Extracts fees per row (not separate fee rows like Etsy)

CSV columns (18): Transaction Date, Type, Order, Card Brand, Card Source,
Payout Status, Payout Date, Payout ID, Available On, Amount, Fee, Net,
Checkout, Payment Method Name, Presentment Amount, Presentment Currency,
Currency, VAT
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from io import StringIO

from app.services.csv_utils import compute_import_hash, parse_money, sniff_delimiter, sniff_encoding

logger = logging.getLogger(__name__)

# --- Constants ---

# Column name mapping (after normalization to lowercase)
COL_TRANSACTION_DATE = "transaction date"
COL_TYPE = "type"
COL_ORDER = "order"
COL_CARD_BRAND = "card brand"
COL_PAYOUT_STATUS = "payout status"
COL_PAYOUT_DATE = "payout date"
COL_PAYOUT_ID = "payout id"
COL_AVAILABLE_ON = "available on"
COL_AMOUNT = "amount"
COL_FEE = "fee"
COL_NET = "net"
COL_CHECKOUT = "checkout"
COL_PAYMENT_METHOD = "payment method name"
COL_PRESENTMENT_AMOUNT = "presentment amount"
COL_PRESENTMENT_CURRENCY = "presentment currency"
COL_CURRENCY = "currency"
COL_VAT = "vat"

REQUIRED_COLUMNS = [COL_TRANSACTION_DATE, COL_TYPE, COL_AMOUNT, COL_FEE, COL_NET]


class ShopifyTransactionType(str, Enum):
    """Shopify transaction types from Payment Transactions export.

    Identified from the Type column. Used to determine:
    - SKR03 account assignment
    - Reverse Charge eligibility (on fees)
    - Internal transfer detection (payouts)
    - Description formatting
    """

    CHARGE = "charge"
    REFUND = "refund"
    CHARGEBACK = "chargeback"
    ADJUSTMENT = "adjustment"
    PAYOUT = "payout"
    RESERVE = "reserve"

    def is_revenue(self) -> bool:
        """Returns True if this type represents revenue (charge or refund)."""
        return self in {ShopifyTransactionType.CHARGE, ShopifyTransactionType.REFUND}

    def is_rc_eligible(self) -> bool:
        """Returns True if fees on this row are subject to §13b Reverse Charge.

        Shopify Payments = Shopify International Ltd (Ireland) is MoR.
        Fees on charge/refund/chargeback rows are EU B2B services → §13b applies.
        """
        return self in {
            ShopifyTransactionType.CHARGE,
            ShopifyTransactionType.REFUND,
            ShopifyTransactionType.CHARGEBACK,
        }

    def suggested_skr03_account(
        self,
        is_kleinunternehmer: bool,
        has_ust_id: bool,
    ) -> int:
        """Returns suggested SKR03 account for the transaction amount.

        4 Scenarios:
        A: Regelbesteuert + USt-ID → Sales on 8400
        B: Kleinunternehmer + USt-ID → Sales on 8195
        C: Regelbesteuert + no USt-ID → Sales on 8400
        D: Kleinunternehmer + no USt-ID → Sales on 8195

        Args:
            is_kleinunternehmer: True if seller is Kleinunternehmer §19 UStG
            has_ust_id: True if USt-ID is registered at Shopify

        Returns:
            SKR03 account number
        """
        # Revenue: charge and refund
        if self in {ShopifyTransactionType.CHARGE, ShopifyTransactionType.REFUND}:
            return 8195 if is_kleinunternehmer else 8400

        # Chargeback reduces revenue (like refund)
        if self == ShopifyTransactionType.CHARGEBACK:
            return 8195 if is_kleinunternehmer else 8400

        # Payout — Geldtransit (internal transfer)
        if self == ShopifyTransactionType.PAYOUT:
            return 1360

        # Adjustment / Reserve — sonstige betriebliche Aufwendungen
        if self in {ShopifyTransactionType.ADJUSTMENT, ShopifyTransactionType.RESERVE}:
            return 4900

        msg = f"No SKR03 account for type {self.value}"
        raise ValueError(msg)

    def suggested_fee_skr03_account(
        self,
        is_kleinunternehmer: bool,
        has_ust_id: bool,
    ) -> int:
        """Returns suggested SKR03 account for the fee component.

        Shopify fees are per-row (Fee column), not separate rows.
        Fee accounting depends on USt-ID registration for §13b.

        Returns:
            SKR03 account number for the fee
        """
        if has_ust_id:
            if is_kleinunternehmer:
                return 3165  # §13b ohne VSt (BU 95)
            return 3125  # §13b mit VSt (BU 94)
        return 4763  # Shopify Gebühren (brutto)

    def format_description(self, order_id: str | None, card_brand: str | None) -> str:
        """Format transaction description based on type."""
        type_labels = {
            ShopifyTransactionType.CHARGE: "Shopify Verkauf",
            ShopifyTransactionType.REFUND: "Shopify Rückerstattung",
            ShopifyTransactionType.CHARGEBACK: "Shopify Rückbuchung",
            ShopifyTransactionType.ADJUSTMENT: "Shopify Anpassung",
            ShopifyTransactionType.PAYOUT: "Shopify Auszahlung",
            ShopifyTransactionType.RESERVE: "Shopify Reserve",
        }

        label = type_labels.get(self, "Shopify Transaktion")

        parts = [label]
        if order_id:
            parts.append(f"#{order_id}")
        if card_brand and self == ShopifyTransactionType.CHARGE:
            parts.append(f"({card_brand})")

        return " ".join(parts)


@dataclass(slots=True)
class ShopifyParsedRow:
    """A parsed Shopify CSV row ready for Transaction creation."""

    date: date
    amount: Decimal
    fee: Decimal
    net: Decimal
    counterparty: str
    description: str
    source_reference: str | None = None
    shopify_type: ShopifyTransactionType = ShopifyTransactionType.CHARGE
    suggested_skr03: int = 4900
    order_id: str | None = None
    is_internal_transfer: bool = False
    is_rc_eligible: bool = False
    rc_fee_amount: Decimal = field(default_factory=lambda: Decimal("0"))
    import_hash: str | None = None
    extra_data: dict = field(default_factory=dict)
    card_brand: str | None = None
    payment_method: str | None = None
    payout_id: str | None = None
    payout_date: date | None = None
    vat: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass(slots=True)
class ShopifyParseResult:
    """Result of parsing a Shopify CSV file."""

    rows: list[ShopifyParsedRow]
    errors: list[str]
    total_rows: int = 0
    skipped_rows: int = 0


class ShopifyParseError(Exception):
    """Raised when Shopify CSV parsing fails."""


# --- Helper Functions ---


def normalize_headers(headers: list[str]) -> dict[str, int]:
    """Normalize Shopify CSV headers to lowercase and map to column indices."""
    return {header.strip().lower(): index for index, header in enumerate(headers)}


def detect_type(type_value: str) -> ShopifyTransactionType:
    """Detect transaction type from Type column."""
    type_lower = type_value.strip().lower()

    type_map = {
        "charge": ShopifyTransactionType.CHARGE,
        "refund": ShopifyTransactionType.REFUND,
        "chargeback": ShopifyTransactionType.CHARGEBACK,
        "adjustment": ShopifyTransactionType.ADJUSTMENT,
        "payout": ShopifyTransactionType.PAYOUT,
        "reserve": ShopifyTransactionType.RESERVE,
    }

    result = type_map.get(type_lower)
    if result is None:
        raise ValueError(f"Unrecognized Shopify transaction type: '{type_value}'")
    return result


def extract_order_id(order_value: str) -> str | None:
    """Extract order number from Order column.

    Shopify format: #3703 or 3703
    """
    cleaned = order_value.strip()
    if not cleaned:
        return None

    # Remove leading # if present
    match = re.match(r"#?(\d+)", cleaned)
    if match:
        return match.group(1)
    return None


def parse_shopify_datetime(datetime_string: str) -> date:
    """Parse Shopify datetime string to date.

    Format: 2026-01-19 12:07:45 +0100
    Also handles: 2026-01-19, 2026-01-19T12:07:45+01:00
    """
    cleaned = datetime_string.strip()
    if not cleaned:
        raise ValueError("Empty datetime string")

    # Try ISO-like with timezone offset: 2026-01-19 12:07:45 +0100
    match = re.match(r"(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}\s+[+-]\d{4}", cleaned)
    if match:
        return datetime.strptime(match.group(0), "%Y-%m-%d %H:%M:%S %z").date()

    # Try ISO date only: 2026-01-19
    match = re.match(r"(\d{4}-\d{2}-\d{2})$", cleaned)
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()

    # Fallback: try dateutil
    from dateutil import parser as dateutil_parser

    return dateutil_parser.parse(cleaned).date()


def compute_shopify_import_hash(
    source_config_id: str,
    transaction_date: date,
    shopify_type: ShopifyTransactionType,
    amount: Decimal,
    order_id: str | None,
    checkout_id: str | None,
) -> str:
    """Compute SHA-256 hash for duplicate detection.

    Uses checkout_id when available (unique per transaction).
    """
    return compute_import_hash(
        source_config_id,
        transaction_date.isoformat(),
        shopify_type.value,
        str(amount.quantize(Decimal("0.01"))),
        order_id or "",
        checkout_id or "",
    )


# --- Main Parser Class ---


class ShopifyStatementParser:
    """Parser for Shopify Payment Transactions CSV exports.

    Usage:
        parser = ShopifyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(raw_bytes, source_config_id)
        for row in result.rows:
            print(row.shopify_type, row.amount, row.fee, row.suggested_skr03)
    """

    def __init__(
        self,
        is_kleinunternehmer: bool = True,
        has_ust_id: bool = True,
    ):
        self.is_kleinunternehmer = is_kleinunternehmer
        self.has_ust_id = has_ust_id

    def parse(self, raw_bytes: bytes, source_config_id: str) -> ShopifyParseResult:
        """Parse raw CSV bytes into ShopifyParsedRow list."""
        import csv

        # Step 1: Detect encoding
        encoding = sniff_encoding(raw_bytes)

        # Step 2: Decode content
        try:
            text_content = raw_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            text_content = raw_bytes.decode("utf-8", errors="replace")

        # Step 3: Detect delimiter from first line
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
            raise ShopifyParseError("Empty CSV file")

        # Step 5: Find and validate header row
        headers = rows_list[0]
        column_map = normalize_headers(headers)

        # Validate required columns
        missing = [col for col in REQUIRED_COLUMNS if col not in column_map]
        if missing:
            raise ShopifyParseError(f"Missing required columns: {missing}. Found: {list(column_map.keys())}")

        # Step 6: Parse data rows
        parsed_rows: list[ShopifyParsedRow] = []
        errors: list[str] = []
        total_rows = 0
        skipped_rows = 0

        for row_index, row in enumerate(rows_list[1:], start=2):
            if not row or all(not cell.strip() for cell in row):
                skipped_rows += 1
                continue

            total_rows += 1

            try:
                parsed_row = self._parse_row(row, column_map, source_config_id, row_index)
                parsed_rows.append(parsed_row)
                # Generate synthetic fee row for rows with non-zero fees
                # (like Etsy's separate fee CSV rows, but synthesized from Fee column)
                if parsed_row.fee != Decimal("0") and parsed_row.shopify_type.is_rc_eligible():
                    fee_row = self._build_fee_row(parsed_row, source_config_id)
                    parsed_rows.append(fee_row)
            except Exception as exc:
                errors.append(f"Row {row_index}: {exc}")
                logger.debug(f"Failed to parse row {row_index}: {exc}", exc_info=True)

        return ShopifyParseResult(
            rows=parsed_rows,
            errors=errors,
            total_rows=total_rows,
            skipped_rows=skipped_rows,
        )

    def _parse_row(
        self,
        row: list[str],
        column_map: dict[str, int],
        source_config_id: str,
        row_index: int,
    ) -> ShopifyParsedRow:
        """Parse a single CSV row into ShopifyParsedRow."""

        def get_cell(column_name: str) -> str:
            index = column_map.get(column_name)
            if index is None or index >= len(row):
                return ""
            return row[index].strip()

        # Extract raw values
        date_str = get_cell(COL_TRANSACTION_DATE)
        type_str = get_cell(COL_TYPE)
        order_str = get_cell(COL_ORDER)
        card_brand = get_cell(COL_CARD_BRAND) or None
        payout_id_str = get_cell(COL_PAYOUT_ID) or None
        payout_date_str = get_cell(COL_PAYOUT_DATE)
        amount_str = get_cell(COL_AMOUNT)
        fee_str = get_cell(COL_FEE)
        net_str = get_cell(COL_NET)
        checkout_str = get_cell(COL_CHECKOUT) or None
        payment_method = get_cell(COL_PAYMENT_METHOD) or None
        currency = get_cell(COL_CURRENCY)
        presentment_currency = get_cell(COL_PRESENTMENT_CURRENCY)
        vat_str = get_cell(COL_VAT)

        # Parse date (timezone-aware format)
        if not date_str:
            raise ValueError("Missing transaction date")
        parsed_date = parse_shopify_datetime(date_str)

        # Detect transaction type
        if not type_str:
            raise ValueError("Missing transaction type")
        shopify_type = detect_type(type_str)

        # Parse amounts
        amount = parse_money(amount_str) if amount_str else Decimal("0")
        fee = parse_money(fee_str) if fee_str else Decimal("0")
        net = parse_money(net_str) if net_str else Decimal("0")
        vat = parse_money(vat_str) if vat_str else Decimal("0")

        # Extract order ID
        order_id = extract_order_id(order_str)

        # Parse payout date if present
        payout_date: date | None = None
        if payout_date_str:
            try:
                payout_date = parse_shopify_datetime(payout_date_str)
            except ValueError:
                pass

        # Currency validation (v1: EUR only)
        actual_currency = currency.upper() if currency else "EUR"

        # Determine counterparty
        if shopify_type.is_revenue():
            counterparty = "Shopify Kunde"
        elif shopify_type == ShopifyTransactionType.PAYOUT:
            counterparty = "Shopify Auszahlung"
        else:
            counterparty = "Shopify International Ltd"

        # Get suggested SKR03 account (for the transaction amount)
        suggested_skr03 = shopify_type.suggested_skr03_account(
            self.is_kleinunternehmer,
            self.has_ust_id,
        )

        # Format description
        description = shopify_type.format_description(order_id, card_brand)

        # Build source reference
        source_reference = self._build_source_reference(shopify_type, order_id, parsed_date, checkout_str)

        # Build extra_data
        if shopify_type.is_revenue():
            category = "revenue"
        elif shopify_type == ShopifyTransactionType.PAYOUT:
            category = "transfer"
        elif shopify_type == ShopifyTransactionType.CHARGEBACK:
            category = "revenue"  # Chargeback reduces revenue
        else:
            category = "other"

        extra_data: dict = {
            "marketplace": "shopify",
            "marketplace_type": shopify_type.value,
            "marketplace_category": category,
        }
        if order_id:
            extra_data["order_id"] = order_id
        if card_brand:
            extra_data["card_brand"] = card_brand
        if payment_method:
            extra_data["payment_method"] = payment_method
        if payout_id_str:
            extra_data["payout_id"] = payout_id_str
        if fee != Decimal("0"):
            extra_data["fee"] = str(fee)
        if actual_currency != "EUR":
            extra_data["original_currency"] = actual_currency
        if presentment_currency and presentment_currency.upper() != actual_currency:
            extra_data["presentment_currency"] = presentment_currency.upper()

        # Compute import hash
        import_hash = compute_shopify_import_hash(
            source_config_id,
            parsed_date,
            shopify_type,
            amount,
            order_id,
            checkout_str,
        )

        # §13b Reverse Charge lives on the synthetic fee row (not on the sale row).
        # The sale row is revenue — RC applies only to the fee expense.

        return ShopifyParsedRow(
            date=parsed_date,
            amount=amount,
            fee=fee,
            net=net,
            counterparty=counterparty,
            description=description,
            source_reference=source_reference,
            shopify_type=shopify_type,
            suggested_skr03=suggested_skr03,
            order_id=order_id,
            is_internal_transfer=shopify_type == ShopifyTransactionType.PAYOUT,
            is_rc_eligible=False,
            rc_fee_amount=Decimal("0"),
            import_hash=import_hash,
            extra_data=extra_data,
            card_brand=card_brand,
            payment_method=payment_method,
            payout_id=payout_id_str,
            payout_date=payout_date,
            vat=vat,
        )

    def _build_fee_row(
        self,
        parent_row: ShopifyParsedRow,
        source_config_id: str,
    ) -> ShopifyParsedRow:
        """Build a synthetic fee row from the Fee column of a parsed charge/refund row.

        Shopify CSV has fees as columns (not separate rows like Etsy).
        This generates a separate fee transaction so fees appear in the UI,
        can be linked to receipts, and are properly booked as expenses.
        """
        fee_amount = -abs(parent_row.fee)  # Fees are expenses (negative)
        fee_description = f"Shopify Gebühr #{parent_row.order_id}" if parent_row.order_id else "Shopify Gebühr"

        # Fee source_reference follows Etsy pattern: Order #3703_FEE
        if parent_row.order_id:
            fee_source_reference = f"Order #{parent_row.order_id}_FEE"
        else:
            fee_source_reference = f"Shopify_fee_{parent_row.date.isoformat()}"

        # Fee SKR03 account (3165/3125/4763 depending on tax scenario)
        fee_skr03 = parent_row.shopify_type.suggested_fee_skr03_account(
            self.is_kleinunternehmer,
            self.has_ust_id,
        )

        # Fee import hash (distinct from parent row)
        fee_import_hash = compute_shopify_import_hash(
            source_config_id,
            parent_row.date,
            parent_row.shopify_type,
            fee_amount,
            parent_row.order_id,
            f"FEE_{parent_row.extra_data.get('checkout_id', '')}",
        )

        fee_extra_data: dict = {
            "marketplace": "shopify",
            "marketplace_type": "fee",
            "marketplace_category": "fee",
        }
        if parent_row.order_id:
            fee_extra_data["order_id"] = parent_row.order_id
        fee_extra_data["fee_source"] = parent_row.shopify_type.value

        return ShopifyParsedRow(
            date=parent_row.date,
            amount=fee_amount,
            fee=Decimal("0"),
            net=fee_amount,
            counterparty="Shopify International Ltd",
            description=fee_description,
            source_reference=fee_source_reference,
            shopify_type=parent_row.shopify_type,
            suggested_skr03=fee_skr03,
            order_id=parent_row.order_id,
            is_internal_transfer=False,
            is_rc_eligible=self.has_ust_id,
            rc_fee_amount=abs(parent_row.fee) if self.has_ust_id else Decimal("0"),
            import_hash=fee_import_hash,
            extra_data=fee_extra_data,
            card_brand=None,
            payment_method=None,
            payout_id=parent_row.payout_id,
            payout_date=parent_row.payout_date,
            vat=Decimal("0"),
        )

    def _build_source_reference(
        self,
        shopify_type: ShopifyTransactionType,
        order_id: str | None,
        transaction_date: date,
        checkout_id: str | None,
    ) -> str:
        """Build source_reference field.

        Format: Order #3703 or Order #3703_REFUND or Payout_YYYY-MM-DD
        """
        if shopify_type == ShopifyTransactionType.PAYOUT:
            return f"Payout_{transaction_date.isoformat()}"

        if order_id:
            suffix_map = {
                ShopifyTransactionType.CHARGE: "",
                ShopifyTransactionType.REFUND: "_REFUND",
                ShopifyTransactionType.CHARGEBACK: "_CHARGEBACK",
            }
            suffix = suffix_map.get(shopify_type, f"_{shopify_type.value.upper()}")
            if suffix:
                return f"Order #{order_id}{suffix}"
            return f"Order #{order_id}"

        # No order ID — use checkout or date-based reference
        if checkout_id:
            return f"Shopify_{shopify_type.value}_{checkout_id}"
        return f"Shopify_{shopify_type.value}_{transaction_date.isoformat()}"
