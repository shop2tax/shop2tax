"""Shared CSV utilities for marketplace parsers.

Pure functions without side effects — encoding detection, delimiter sniffing,
date parsing, money parsing, and import hash computation.
Used by Etsy, Shopify, Amazon, and generic CSV parsers.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from charset_normalizer import from_bytes

from app.core.constants import GERMAN_TO_ENGLISH_MONTHS


def sniff_encoding(raw_bytes: bytes) -> str:
    """Detect encoding of CSV content.

    Priority: UTF-8 with BOM → UTF-8 → Windows-1252 (German Excel default)
    Falls back to charset_normalizer for other encodings.
    """
    # Handle BOM
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"

    # Try UTF-8 first (most common)
    try:
        raw_bytes.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # Try Windows-1252 (German Excel exports)
    try:
        raw_bytes.decode("windows-1252")
        return "windows-1252"
    except UnicodeDecodeError:
        pass

    # Fallback to charset_normalizer
    result = from_bytes(raw_bytes)
    best_match = result.best()
    if best_match:
        return best_match.encoding

    return "utf-8"  # Last resort


def sniff_delimiter(first_line: str) -> str:
    """Detect CSV delimiter from first line.

    Supports comma, semicolon, and tab delimiters.
    """
    # Count occurrences
    comma_count = first_line.count(",")
    semicolon_count = first_line.count(";")
    tab_count = first_line.count("\t")

    # Pick the most frequent
    if semicolon_count > comma_count and semicolon_count > tab_count:
        return ";"
    if tab_count > comma_count:
        return "\t"
    return ","


def parse_localized_date(date_string: str) -> date:
    """Parse date string with German or English month names.

    Handles formats:
    - "31. January 2026" (Etsy default)
    - "31. Januar 2026" (German)
    - "January 31, 2026" (US)
    - "31 January 2026" (UK)
    - "2026-01-31" (ISO)
    - "31.01.2026" (German short)
    """
    cleaned = date_string.strip()

    if not cleaned:
        raise ValueError("Empty date string")

    # Replace German month names with English
    for german, english in GERMAN_TO_ENGLISH_MONTHS.items():
        cleaned = re.sub(rf"\b{german}\b", english, cleaned, flags=re.IGNORECASE)

    # Try dateutil parser (handles many formats)
    try:
        from dateutil import parser as dateutil_parser

        return dateutil_parser.parse(cleaned, dayfirst=True).date()
    except (ValueError, ImportError):
        pass

    # Fallback: manual parsing for common formats
    from datetime import datetime

    formats = [
        "%d. %B %Y",  # 31. January 2026
        "%B %d, %Y",  # January 31, 2026
        "%d %B %Y",  # 31 January 2026
        "%Y-%m-%d",  # 2026-01-31
        "%d.%m.%Y",  # 31.01.2026
        "%d.%m.%y",  # 31.01.26
    ]

    for date_format in formats:
        try:
            return datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"Cannot parse date: {date_string}")


def parse_money(amount_string: str) -> Decimal:
    """Parse monetary amount string to Decimal.

    Handles:
    - Currency symbols: €, $, £
    - Thousands separators (German: 1.234,56 / English: 1,234.56)
    - Negative amounts: -123.45, (123.45), -€123.45

    Always returns Decimal, never float.
    """
    cleaned = amount_string.strip()

    if not cleaned or cleaned == "--":
        return Decimal("0")

    # Remove currency symbols
    cleaned = cleaned.replace("€", "").replace("$", "").replace("£", "").replace(" ", "").strip()

    # Handle parentheses notation for negatives: (123.45) → -123.45
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]

    # Detect format: German (1.234,56) vs English (1,234.56)
    # If comma appears after period → German format
    comma_pos = cleaned.rfind(",")
    period_pos = cleaned.rfind(".")

    if comma_pos > period_pos and comma_pos > 0:
        # German format: 1.234,56 → remove thousands separator (.), replace decimal (,) with (.)
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif period_pos > comma_pos and period_pos > 0:
        # English format: 1,234.56 → remove thousands separator (,)
        cleaned = cleaned.replace(",", "")
    elif comma_pos > 0 and period_pos < 0:
        # Only comma present: assume German decimal (123,45)
        cleaned = cleaned.replace(",", ".")
    # If only period or neither, assume English format (123.45 or 123)

    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"Cannot parse amount: {amount_string}") from exc


def compute_import_hash(*fields: str) -> str:
    """Compute SHA-256 hash for duplicate detection.

    Callers normalize their fields before passing them in.
    All fields are joined with "|" and hashed.

    Returns:
        64-character hex SHA-256 hash
    """
    import hashlib

    hash_input = "|".join(fields)
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
