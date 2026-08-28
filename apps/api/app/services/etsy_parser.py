"""Etsy Statement Parser — dedicated CSV parser for Etsy monthly statements.

This parser understands the Etsy CSV format and automatically:
1. Detects encoding (UTF-8 with BOM, Windows-1252, etc.)
2. Detects delimiter (comma vs semicolon)
3. Parses German and English date formats
4. Categorizes all 13 transaction types to correct SKR03 accounts
5. Handles 4 tax scenarios (Kleinunternehmer × USt-ID registration)
6. Extracts Order IDs for linking related transactions

CSV columns: Datum, Art, Titel, Info, Währung, Betrag, Gebühren & Steuern, Netto, Steuerliche Angaben
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from io import StringIO

from app.services.csv_utils import compute_import_hash, parse_localized_date, parse_money, sniff_delimiter, sniff_encoding

logger = logging.getLogger(__name__)

# --- Constants ---

# Expected Etsy CSV columns (German headers — English headers also supported via normalization)
ETSY_COLUMNS_DE = ["datum", "art", "titel", "info", "währung", "betrag", "gebühren & steuern", "netto", "steuerliche angaben"]
ETSY_COLUMNS_EN = ["date", "type", "title", "info", "currency", "amount", "fees & taxes", "net", "taxes"]

# Column index mapping (after normalization)
COL_DATE = "datum"
COL_TYPE = "art"
COL_TITLE = "titel"
COL_INFO = "info"
COL_CURRENCY = "währung"
COL_AMOUNT = "betrag"
COL_FEES = "gebühren & steuern"
COL_NET = "netto"
COL_TAXES = "steuerliche angaben"


class EtsyTransactionType(str, Enum):
    """Etsy transaction types (parser-internal, not persisted to DB).

    Identified from CSV Art + Titel columns. Used to determine:
    - SKR03 account assignment
    - Reverse Charge eligibility
    - Amount sign (income vs expense)
    - Description formatting
    """

    # Sales
    SALE = "sale"
    REFUND = "refund"

    # Tax (durchlaufender Posten)
    SALES_TAX = "sales_tax"

    # Fees (subject to Reverse Charge when USt-ID registered)
    FEE_TRANSACTION_SHIPPING = "fee_transaction_shipping"
    FEE_TRANSACTION_ITEM = "fee_transaction_item"
    FEE_PROCESSING = "fee_processing"
    FEE_LISTING = "fee_listing"

    # Credits (fee reversals)
    CREDIT_TRANSACTION = "credit_transaction"
    CREDIT_PROCESSING = "credit_processing"
    CREDIT_LISTING = "credit_listing"

    # Marketing (subject to Reverse Charge when USt-ID registered)
    MARKETING_ADS = "marketing_ads"
    MARKETING_OFFSITE = "marketing_offsite"

    # Payout
    PAYOUT = "payout"

    def is_fee(self) -> bool:
        """Returns True if this is a fee type (negative amount, expense)."""
        return self in {
            EtsyTransactionType.FEE_TRANSACTION_SHIPPING,
            EtsyTransactionType.FEE_TRANSACTION_ITEM,
            EtsyTransactionType.FEE_PROCESSING,
            EtsyTransactionType.FEE_LISTING,
        }

    def is_credit(self) -> bool:
        """Returns True if this is a credit type (fee reversal, positive amount)."""
        return self in {
            EtsyTransactionType.CREDIT_TRANSACTION,
            EtsyTransactionType.CREDIT_PROCESSING,
            EtsyTransactionType.CREDIT_LISTING,
        }

    def is_marketing(self) -> bool:
        """Returns True if this is a marketing expense."""
        return self in {
            EtsyTransactionType.MARKETING_ADS,
            EtsyTransactionType.MARKETING_OFFSITE,
        }

    def is_rc_eligible(self) -> bool:
        """Returns True if this type is subject to §13b Reverse Charge (when USt-ID registered).

        Fees and marketing from Etsy Ireland UC are EU B2B services → §13b applies.
        """
        return self.is_fee() or self.is_credit() or self.is_marketing()

    def is_revenue(self) -> bool:
        """Returns True if this affects revenue (sale or refund)."""
        return self in {EtsyTransactionType.SALE, EtsyTransactionType.REFUND}

    def suggested_skr03_account(
        self,
        is_kleinunternehmer: bool,
        has_ust_id: bool,
    ) -> int:
        """Returns suggested SKR03 account based on tax scenario.

        4 Scenarios:
        A: Regelbesteuert + USt-ID → Fees on 3125 (§13b mit VSt), Sales on 8400
        B: Kleinunternehmer + USt-ID → Fees on 3165 (§13b ohne VSt), Sales on 8195
        C: Regelbesteuert + no USt-ID → Fees on 4761 (brutto, VSt from Rechnung), Sales on 8400
        D: Kleinunternehmer + no USt-ID → Fees on 4761 (brutto, no VSt), Sales on 8195

        Args:
            is_kleinunternehmer: True if seller is Kleinunternehmer §19 UStG
            has_ust_id: True if USt-ID is registered at Etsy (Reverse Charge applies)

        Returns:
            SKR03 account number
        """
        # Revenue accounts
        if self == EtsyTransactionType.SALE:
            return 8195 if is_kleinunternehmer else 8400

        if self == EtsyTransactionType.REFUND:
            # Refund reduces revenue → same account as sale (Erlösminderung)
            return 8195 if is_kleinunternehmer else 8400

        # Sales Tax — durchlaufender Posten (pass-through)
        if self == EtsyTransactionType.SALES_TAX:
            return 1590

        # Payout — Geldtransit (internal transfer)
        if self == EtsyTransactionType.PAYOUT:
            return 1360  # Geldtransit

        # Fees and Marketing — depends on USt-ID registration
        if self.is_rc_eligible():
            if has_ust_id:
                # Scenarios A/B: Reverse Charge applies
                if is_kleinunternehmer:
                    return 3165  # §13b ohne VSt (BU 95)
                return 3125  # §13b mit VSt (BU 94)
            # Scenarios C/D: No Reverse Charge, Etsy charges brutto
            return 4761  # Etsy Gebühren (brutto)

        # Remaining types (SALE, REFUND, SALES_TAX, PAYOUT) are handled above
        msg = f"No SKR03 account for type {self.value}"
        raise ValueError(msg)

    def format_description(self, title: str, order_id: str | None) -> str:
        """Format transaction description based on type."""
        type_labels = {
            EtsyTransactionType.SALE: "Etsy Verkauf",
            EtsyTransactionType.REFUND: "Etsy Rückerstattung",
            EtsyTransactionType.SALES_TAX: "Etsy Sales Tax",
            EtsyTransactionType.FEE_TRANSACTION_SHIPPING: "Etsy Transaktionsgebühr Versand",
            EtsyTransactionType.FEE_TRANSACTION_ITEM: "Etsy Transaktionsgebühr",
            EtsyTransactionType.FEE_PROCESSING: "Etsy Zahlungsabwicklung",
            EtsyTransactionType.FEE_LISTING: "Etsy Einstellgebühr",
            EtsyTransactionType.CREDIT_TRANSACTION: "Etsy Gutschrift Transaktionsgebühr",
            EtsyTransactionType.CREDIT_PROCESSING: "Etsy Gutschrift Zahlungsabwicklung",
            EtsyTransactionType.CREDIT_LISTING: "Etsy Gutschrift Einstellgebühr",
            EtsyTransactionType.MARKETING_ADS: "Etsy Ads",
            EtsyTransactionType.MARKETING_OFFSITE: "Etsy Offsite Ads",
            EtsyTransactionType.PAYOUT: "Etsy Auszahlung",
        }

        label = type_labels.get(self, "Etsy Transaktion")

        if order_id:
            return f"{label} #{order_id}"
        return f"{label}: {title[:50]}" if title else label


@dataclass(slots=True)
class EtsyParsedRow:
    """A parsed Etsy CSV row ready for Transaction creation.

    Extends the concept of ParsedRow with Etsy-specific fields.
    """

    date: date
    amount: Decimal
    counterparty: str
    description: str
    source_reference: str | None = None
    etsy_type: EtsyTransactionType = EtsyTransactionType.SALE
    suggested_skr03: int = 4900
    order_id: str | None = None
    is_internal_transfer: bool = False
    is_rc_eligible: bool = False  # §13b Reverse Charge eligible (set at parse time)
    rc_fee_amount: Decimal = field(default_factory=lambda: Decimal("0"))  # Fee amount for RC calculation
    import_hash: str | None = None
    extra_data: dict = field(default_factory=dict)
    raw_row: dict | None = None


@dataclass(slots=True)
class EtsyParseResult:
    """Result of parsing an Etsy CSV file."""

    rows: list[EtsyParsedRow]
    errors: list[str]
    total_rows: int = 0
    skipped_rows: int = 0


class EtsyParseError(Exception):
    """Raised when Etsy CSV parsing fails."""

    pass


# --- CSV Robustness Functions ---


def normalize_headers(headers: list[str]) -> dict[str, int]:
    """Normalize headers to lowercase and map to column indices.

    Handles both German and English Etsy headers.
    Returns: {normalized_name: column_index}
    """
    # Header aliases: normalized → standard name
    aliases = {
        # German
        "datum": COL_DATE,
        "art": COL_TYPE,
        "titel": COL_TITLE,
        "info": COL_INFO,
        "währung": COL_CURRENCY,
        "waehrung": COL_CURRENCY,
        "betrag": COL_AMOUNT,
        "gebühren & steuern": COL_FEES,
        "gebuehren & steuern": COL_FEES,
        "netto": COL_NET,
        "steuerliche angaben": COL_TAXES,
        # English
        "date": COL_DATE,
        "type": COL_TYPE,
        "title": COL_TITLE,
        "currency": COL_CURRENCY,
        "amount": COL_AMOUNT,
        "fees & taxes": COL_FEES,
        "net": COL_NET,
        "taxes": COL_TAXES,
    }

    result = {}
    for index, header in enumerate(headers):
        normalized = header.strip().lower()
        standard_name = aliases.get(normalized, normalized)
        result[standard_name] = index

    return result


def is_header_row(row: list[str]) -> bool:
    """Check if row is a header row (skip inline headers from merged CSVs)."""
    if not row:
        return False

    first_cell = row[0].strip().lower()
    return first_cell in {"datum", "date", "art", "type"}


def detect_type(art: str, titel: str) -> EtsyTransactionType:
    """Detect transaction type from Art and Titel columns.

    Pattern matching based on FR-2 requirements.
    """
    art_lower = art.strip().lower()
    titel_lower = titel.strip().lower()

    # Sale
    if art_lower == "sale" or art_lower == "verkauf":
        return EtsyTransactionType.SALE

    # Refund
    if art_lower == "refund" or art_lower == "rückerstattung" or "refund" in titel_lower:
        return EtsyTransactionType.REFUND

    # Tax (Sales Tax collected by Etsy as Marketplace Facilitator)
    if art_lower == "tax" or "sales tax" in titel_lower or "mehrwertsteuer" in titel_lower:
        return EtsyTransactionType.SALES_TAX

    # Payout
    if art_lower in {"payout", "überweisung", "transfer"}:
        return EtsyTransactionType.PAYOUT
    if "€" in titel and ("überwiesen" in titel_lower or "bankkonto" in titel_lower):
        return EtsyTransactionType.PAYOUT

    # Marketing (check BEFORE fee block — Etsy Ads appear with Art="Fee" too)
    if art_lower == "marketing" or art_lower == "werbung":
        if "offsite" in titel_lower:
            return EtsyTransactionType.MARKETING_OFFSITE
        return EtsyTransactionType.MARKETING_ADS

    # Ads detection by title (Art can be "Fee" for ads)
    if "offsite ads" in titel_lower or "offsite-anzeigen" in titel_lower:
        return EtsyTransactionType.MARKETING_OFFSITE
    if "etsy ads" in titel_lower or "etsy-anzeigen" in titel_lower:
        return EtsyTransactionType.MARKETING_ADS

    # Fees (Art="Fee" or "Gebühr")
    if art_lower == "fee" or art_lower == "gebühr":
        # Credits FIRST (before fee patterns, since "Credit for transaction fee" contains "transaction fee")
        if "credit" in titel_lower or "gutschrift" in titel_lower:
            if "transaction" in titel_lower or "transaktions" in titel_lower:
                return EtsyTransactionType.CREDIT_TRANSACTION
            if "processing" in titel_lower or "abwicklung" in titel_lower:
                return EtsyTransactionType.CREDIT_PROCESSING
            if "listing" in titel_lower or "einstell" in titel_lower:
                return EtsyTransactionType.CREDIT_LISTING
            return EtsyTransactionType.CREDIT_TRANSACTION  # Default credit type

        # Transaction fee: Shipping
        if "shipping" in titel_lower or "versand" in titel_lower:
            return EtsyTransactionType.FEE_TRANSACTION_SHIPPING

        # Processing fee
        if "processing" in titel_lower or "abwicklung" in titel_lower or "zahlungsabwicklung" in titel_lower:
            return EtsyTransactionType.FEE_PROCESSING

        # Listing fee
        if "listing" in titel_lower or "einstellgebühr" in titel_lower or "0,20 usd" in titel_lower:
            return EtsyTransactionType.FEE_LISTING

        # Transaction fee: Item (generic — after more specific patterns)
        if "transaction fee" in titel_lower or "transaktionsgebühr" in titel_lower:
            return EtsyTransactionType.FEE_TRANSACTION_ITEM

        # Fallback to item fee
        return EtsyTransactionType.FEE_TRANSACTION_ITEM

    raise ValueError(f"Unrecognized Etsy transaction type: Art='{art}', Titel='{titel[:50]}'")


def extract_order_id(info: str, titel: str) -> str | None:
    """Extract Order ID from Info or Titel column.

    Patterns:
    - "Order #3964911563"
    - "Bestellnr. 3964911563"
    - "#3964911563"
    """
    combined = f"{info} {titel}"

    # Pattern 1: Order #xxx or Bestellnr. xxx
    match = re.search(r"(?:order\s*#?|bestellnr\.?\s*)(\d+)", combined, re.IGNORECASE)
    if match:
        return match.group(1)

    # Pattern 2: Standalone #xxx (at least 8 digits = likely order ID)
    match = re.search(r"#(\d{8,})", combined)
    if match:
        return match.group(1)

    return None


def compute_etsy_import_hash(
    source_config_id: str,
    transaction_date: date,
    etsy_type: EtsyTransactionType,
    amount: Decimal,
    order_id: str | None,
    title: str,
) -> str:
    """Compute SHA-256 hash for duplicate detection.

    Includes title to prevent collisions when multiple listing fees
    occur on the same day with the same amount.
    """
    return compute_import_hash(
        source_config_id,
        transaction_date.isoformat(),
        etsy_type.value,
        str(amount.quantize(Decimal("0.01"))),
        order_id or "",
        title.strip().lower()[:50],
    )


# --- Main Parser Class ---


class EtsyStatementParser:
    """Parser for Etsy monthly statement CSV files.

    Usage:
        parser = EtsyStatementParser(is_kleinunternehmer=True, has_ust_id=True)
        result = parser.parse(raw_bytes, source_config_id)
        for row in result.rows:
            print(row.etsy_type, row.amount, row.suggested_skr03)
    """

    def __init__(
        self,
        is_kleinunternehmer: bool = True,
        has_ust_id: bool = True,
    ):
        """Initialize parser with tax scenario configuration.

        Args:
            is_kleinunternehmer: True if seller is Kleinunternehmer §19 UStG
            has_ust_id: True if USt-ID is registered at Etsy
        """
        self.is_kleinunternehmer = is_kleinunternehmer
        self.has_ust_id = has_ust_id

    def parse(self, raw_bytes: bytes, source_config_id: str) -> EtsyParseResult:
        """Parse raw CSV bytes into EtsyParsedRow list.

        Args:
            raw_bytes: Raw CSV file content
            source_config_id: UUID of the TransactionSourceConfig

        Returns:
            EtsyParseResult with parsed rows and any errors
        """
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

        # Step 4: Parse CSV (fall back to QUOTE_NONE if unescaped quotes break parsing)
        try:
            reader = csv.reader(StringIO(text_content), delimiter=delimiter)
            rows_list = list(reader)
        except csv.Error:
            reader = csv.reader(StringIO(text_content), delimiter=delimiter, quoting=csv.QUOTE_NONE)
            rows_list = list(reader)

        if not rows_list:
            raise EtsyParseError("Empty CSV file")

        # Step 5: Find and validate header row
        header_index = 0
        for index, row in enumerate(rows_list):
            if row and is_header_row(row):
                header_index = index
                break

        headers = rows_list[header_index]
        column_map = normalize_headers(headers)

        # Validate required columns exist
        required_columns = [COL_DATE, COL_TYPE, COL_TITLE, COL_AMOUNT]
        missing = [col for col in required_columns if col not in column_map]
        if missing:
            raise EtsyParseError(f"Missing required columns: {missing}. Found: {list(column_map.keys())}")

        # Step 6: Parse data rows
        parsed_rows: list[EtsyParsedRow] = []
        errors: list[str] = []
        total_rows = 0
        skipped_rows = 0

        for row_index, row in enumerate(rows_list[header_index + 1 :], start=header_index + 2):
            if not row or all(not cell.strip() for cell in row):
                skipped_rows += 1
                continue

            # Skip inline headers (from merged CSVs)
            if is_header_row(row):
                skipped_rows += 1
                continue

            total_rows += 1

            try:
                parsed_row = self._parse_row(row, column_map, source_config_id, row_index)
                parsed_rows.append(parsed_row)
            except Exception as exc:
                errors.append(f"Row {row_index}: {exc}")
                logger.debug(f"Failed to parse row {row_index}: {exc}", exc_info=True)

        return EtsyParseResult(
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
    ) -> EtsyParsedRow:
        """Parse a single CSV row into EtsyParsedRow."""

        def get_cell(column_name: str) -> str:
            index = column_map.get(column_name)
            if index is None or index >= len(row):
                return ""
            return row[index].strip()

        # Extract raw values
        date_str = get_cell(COL_DATE)
        art = get_cell(COL_TYPE)
        titel = get_cell(COL_TITLE)
        info = get_cell(COL_INFO)
        currency = get_cell(COL_CURRENCY)
        amount_str = get_cell(COL_AMOUNT)
        net_str = get_cell(COL_NET)

        # Parse date
        if not date_str:
            raise ValueError("Missing date")
        parsed_date = parse_localized_date(date_str)

        # Detect transaction type
        etsy_type = detect_type(art, titel)

        # Parse amount (use Net column if available, otherwise Amount)
        # For fees, Etsy shows gross in Betrag and net in Netto
        amount_to_parse = net_str if net_str and net_str != "--" else amount_str

        # Payout rows often have "--" in all amount columns — extract from title
        if etsy_type == EtsyTransactionType.PAYOUT and (not amount_to_parse or amount_to_parse == "--"):
            payout_match = re.search(r"€([\d.,]+)", titel)
            if payout_match:
                amount = parse_money(payout_match.group(1))
            else:
                raise ValueError("Payout row with no amount in columns or title")
        elif not amount_to_parse or amount_to_parse == "--":
            raise ValueError("Missing amount")
        else:
            amount = parse_money(amount_to_parse)

        # Also try title extraction if parsed amount is zero (backup)
        if etsy_type == EtsyTransactionType.PAYOUT and amount == Decimal("0"):
            payout_match = re.search(r"€([\d.,]+)", titel)
            if payout_match:
                amount = parse_money(payout_match.group(1))

        # Extract order ID
        order_id = extract_order_id(info, titel)

        # Determine counterparty
        if etsy_type.is_revenue():
            # For sales, counterparty could be customer name (from Billbee later)
            counterparty = "Etsy Kunde"
        elif etsy_type == EtsyTransactionType.PAYOUT:
            counterparty = "Etsy Auszahlung"
        else:
            # For fees, counterparty is Etsy
            counterparty = "Etsy Ireland UC"

        # Get suggested SKR03 account
        suggested_skr03 = etsy_type.suggested_skr03_account(
            self.is_kleinunternehmer,
            self.has_ust_id,
        )

        # Format description
        description = etsy_type.format_description(titel, order_id)

        # Build source reference
        source_reference = self._build_source_reference(etsy_type, order_id, parsed_date)

        # Build extra_data for Transaction.extra_data (D11)
        # marketplace_category: standardized across all marketplace parsers for API filtering
        if etsy_type.is_fee() or etsy_type.is_credit():
            category = "fee"
        elif etsy_type.is_marketing():
            category = "marketing"
        elif etsy_type.is_revenue():
            category = "revenue"
        elif etsy_type == EtsyTransactionType.PAYOUT:
            category = "transfer"
        else:
            category = "other"

        extra_data = {
            "marketplace": "etsy",
            "marketplace_type": etsy_type.value,
            "marketplace_category": category,
        }
        if order_id:
            extra_data["order_id"] = order_id
        if currency and currency.upper() != "EUR":
            extra_data["original_currency"] = currency.upper()
            # For listing fees, store original USD amount
            if etsy_type == EtsyTransactionType.FEE_LISTING and "usd" in titel.lower():
                usd_match = re.search(r"([\d.,]+)\s*usd", titel.lower())
                if usd_match:
                    extra_data["original_amount"] = usd_match.group(1)

        # Compute import hash
        row_import_hash = compute_etsy_import_hash(
            source_config_id,
            parsed_date,
            etsy_type,
            amount,
            order_id,
            titel,
        )

        # §13b Reverse Charge: eligible when USt-ID registered AND transaction type is fee/credit/marketing
        is_rc_eligible = etsy_type.is_rc_eligible() and self.has_ust_id
        # For Etsy, RC fee amount is the absolute amount of fee/credit/marketing rows
        rc_fee_amount = abs(amount) if is_rc_eligible else Decimal("0")

        return EtsyParsedRow(
            date=parsed_date,
            amount=amount,
            counterparty=counterparty,
            description=description,
            source_reference=source_reference,
            etsy_type=etsy_type,
            suggested_skr03=suggested_skr03,
            order_id=order_id,
            is_internal_transfer=etsy_type in {EtsyTransactionType.PAYOUT, EtsyTransactionType.SALES_TAX},
            is_rc_eligible=is_rc_eligible,
            rc_fee_amount=rc_fee_amount,
            import_hash=row_import_hash,
            extra_data=extra_data,
            raw_row=dict(zip(column_map.keys(), row)),
        )

    def _build_source_reference(
        self,
        etsy_type: EtsyTransactionType,
        order_id: str | None,
        transaction_date: date,
    ) -> str:
        """Build source_reference field following PayPal fee pattern.

        Format: {order_id}_{TYPE} or Payout_YYYY-MM-DD
        """
        if etsy_type == EtsyTransactionType.PAYOUT:
            return f"Payout_{transaction_date.isoformat()}"

        if order_id:
            suffix_map = {
                EtsyTransactionType.SALE: "",
                EtsyTransactionType.REFUND: "_REFUND",
                EtsyTransactionType.SALES_TAX: "_TAX",
                EtsyTransactionType.FEE_TRANSACTION_SHIPPING: "_FEE_SHIPPING",
                EtsyTransactionType.FEE_TRANSACTION_ITEM: "_FEE_ITEM",
                EtsyTransactionType.FEE_PROCESSING: "_FEE_PROCESSING",
                EtsyTransactionType.FEE_LISTING: "_FEE_LISTING",
                EtsyTransactionType.CREDIT_TRANSACTION: "_CREDIT_TRANSACTION",
                EtsyTransactionType.CREDIT_PROCESSING: "_CREDIT_PROCESSING",
                EtsyTransactionType.CREDIT_LISTING: "_CREDIT_LISTING",
                EtsyTransactionType.MARKETING_ADS: "_ADS",
                EtsyTransactionType.MARKETING_OFFSITE: "_OFFSITE_ADS",
            }
            suffix = suffix_map.get(etsy_type, f"_{etsy_type.value.upper()}")

            if suffix:
                return f"Order #{order_id}{suffix}"
            return f"Order #{order_id}"

        # No order ID — use date-based reference
        return f"Etsy_{etsy_type.value}_{transaction_date.isoformat()}"
