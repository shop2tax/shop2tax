"""Generic CSV parser with user-defined column mapping.

This service provides:
1. Automatic detection of CSV options (delimiter, encoding, header, date/amount format)
2. Parsing with user-provided CsvMappingProfile
3. Import hash computation for duplicate detection

Replaces bank-specific parsers (DKB, Finom) with a universal mapper.
Marketplace parsers (Etsy, Amazon, Shopify, Stripe) remain unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from datetime import date as date_type
from decimal import Decimal, InvalidOperation
from enum import Enum
from io import StringIO
from typing import Protocol, runtime_checkable

import pandas as pd
from charset_normalizer import from_bytes

from app.services.csv_utils import compute_import_hash as _shared_compute_import_hash


@runtime_checkable
class CsvMappingLike(Protocol):
    """Duck-type interface for CSV mapping config.

    Satisfied by both CsvMappingProfile (ORM model) and MappingAdapter (router adapter).
    """

    delimiter: str
    encoding: str
    has_header: bool
    skip_rows: int
    date_format: str | None
    amount_format: str | None
    column_date: str | None
    column_amount: str | None
    column_counterparty: str | None
    column_description: str | None
    column_reference: str | None
    column_filter: str | None
    filter_include_values: list | None


@dataclass(slots=True)
class ParsedRow:
    """A single parsed CSV row ready for Transaction creation.

    Attributes:
        date: Transaction date
        amount: Transaction amount (positive=income, negative=expense)
        counterparty: Name of payer/payee
        description: Transaction description/purpose
        source_reference: Optional source-specific reference ID
        raw_row: Original row data for debugging
    """

    date: date_type | None = None
    amount: Decimal | None = None
    counterparty: str | None = None
    description: str | None = None
    source_reference: str | None = None
    raw_row: dict | None = None


class DateAmbiguity(str, Enum):
    """Date format ambiguity status."""

    UNAMBIGUOUS = "unambiguous"  # Format is clear (e.g., 2026-02-20)
    AMBIGUOUS = "ambiguous"  # Could be DD/MM or MM/DD
    UNKNOWN = "unknown"  # Could not determine format


@dataclass(frozen=True, slots=True)
class SuggestedColumns:
    """Auto-detected column assignments based on sample values."""

    column_date: str | None = None
    column_amount: str | None = None
    column_counterparty: str | None = None
    column_description: str | None = None
    column_reference: str | None = None


@dataclass(frozen=True, slots=True)
class DetectedCsvOptions:
    """Auto-detected CSV parsing options."""

    delimiter: str
    encoding: str
    has_header: bool
    skip_rows: int
    date_format: str | None  # strptime format, None if ambiguous
    date_ambiguity: DateAmbiguity
    amount_format: str  # "german" or "english"
    column_headers: list[str]
    sample_values: dict[str, list[str]]  # column_name -> first 5 values
    suggested_columns: SuggestedColumns | None = None


@dataclass(frozen=True, slots=True)
class GenericParseResult:
    """Result of parsing CSV with mapping."""

    rows: list[ParsedRow]
    errors: list[str]  # Per-row error messages for failed rows
    filtered_count: int = 0  # Rows removed by filter
    kept_count: int = 0  # Rows kept after filter


class GenericCsvParseError(Exception):
    """Raised when generic CSV parsing fails."""

    pass


# --- CSV Formula Injection Protection ---


def sanitize_cell_value(value: str) -> str:
    """Sanitize CSV cell value to prevent formula injection.

    Strips leading characters that could be interpreted as formulas:
    - = (formula)
    - + (formula or positive number)
    - - (formula or negative number - only strip if not followed by digit)
    - @ (mention/formula)

    Args:
        value: Raw cell value

    Returns:
        Sanitized value
    """
    if not value:
        return value

    value = value.strip()

    # Pattern: starts with dangerous char, but NOT - followed by digit (negative number)
    if value.startswith("="):
        return value[1:].strip()
    if value.startswith("@"):
        return value[1:].strip()
    if value.startswith("+") and (len(value) < 2 or not value[1].isdigit()):
        return value[1:].strip()
    if value.startswith("-") and (len(value) < 2 or not value[1].isdigit()):
        return value[1:].strip()

    return value


# --- Encoding Detection ---


def detect_encoding(content: bytes) -> str:
    """Detect encoding of CSV content.

    Uses charset-normalizer (transitive dep via requests).

    Args:
        content: Raw CSV bytes

    Returns:
        Detected encoding name (e.g., "utf-8", "iso-8859-1")
    """
    # Handle BOM (UTF-8 with BOM is common in Excel exports)
    if content.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"

    result = from_bytes(content)
    best_match = result.best()

    if best_match is None:
        return "utf-8"  # Fallback

    encoding = best_match.encoding
    # Normalize common aliases
    if encoding.lower() in ("ascii", "utf8"):
        return "utf-8"

    return encoding


# --- Delimiter Detection ---


def detect_delimiter(content: str) -> str:
    """Detect CSV delimiter from content.

    Tries common delimiters and picks the one that produces
    the most consistent column count across rows.

    Args:
        content: CSV content as string

    Returns:
        Detected delimiter character
    """
    candidates = [",", ";", "\t", "|"]
    best_delimiter = ","
    best_consistency = 0

    for delimiter in candidates:
        try:
            # Read first 10 lines
            lines = content.strip().split("\n")[:10]
            column_counts = []

            for line in lines:
                if line.strip():
                    # Simple split (doesn't handle quoted fields perfectly, but good enough for detection)
                    count = len(line.split(delimiter))
                    column_counts.append(count)

            if not column_counts:
                continue

            # Consistency: how many rows have the same column count as the first row
            mode_count = column_counts[0]
            consistency = sum(1 for c in column_counts if c == mode_count) / len(column_counts)

            # Prefer delimiters that give > 1 column and high consistency
            if mode_count > 1 and consistency > best_consistency:
                best_consistency = consistency
                best_delimiter = delimiter

        except Exception:
            continue

    return best_delimiter


# --- Skip Rows Detection ---


def detect_skip_rows(text_content: str, delimiter: str) -> int:
    """Detect metadata rows before the actual header/data.

    Many bank CSVs (DKB, ING, etc.) have metadata rows at the top:
    - Account info, date ranges, balances
    - Empty rows
    - Fewer columns than the data section

    Strategy: Find the first row where the column count matches the
    dominant (most frequent) column count. Everything before it is metadata.

    Args:
        text_content: Decoded CSV content
        delimiter: Detected delimiter

    Returns:
        Number of rows to skip (0 if no metadata detected)
    """
    lines = text_content.strip().split("\n")
    if len(lines) < 3:
        return 0

    # Count columns per row (using csv module for proper quoting)
    import csv

    column_counts: list[int] = []
    reader = csv.reader(lines, delimiter=delimiter, quotechar='"')
    for row in reader:
        # Filter out completely empty rows as having 0 columns
        non_empty = [cell for cell in row if cell.strip()]
        column_counts.append(len(non_empty))

    if not column_counts:
        return 0

    # Find the data column count: use total columns (including empty) from the row
    # with the most total columns. This avoids miscounting when data rows have
    # optional empty fields (e.g., Finom: header has 20 cols, data rows 18 non-empty).
    # Count total columns (not just non-empty) for consistency check.
    import csv as csv_module

    total_column_counts: list[int] = []
    reader2 = csv_module.reader(lines, delimiter=delimiter, quotechar='"')
    for row in reader2:
        total_column_counts.append(len(row))

    from collections import Counter

    count_freq = Counter(column_counts)
    # Sort by column count descending, pick the highest with >= 2 occurrences
    data_column_count = 0
    for count, frequency in sorted(count_freq.items(), reverse=True):
        if count >= 2 and frequency >= 2:
            data_column_count = count
            break

    # Fallback: if no count appears twice, use the maximum
    if data_column_count == 0:
        data_column_count = max(column_counts)

    if data_column_count < 2:
        return 0

    # Find the first row that belongs to the data region.
    # A row belongs to data if it has >= data_column_count non-empty cells.
    # This handles headers that have MORE filled cells than some data rows
    # (e.g., header has 20/20 non-empty, data rows have 18/20 non-empty).
    for index, count in enumerate(column_counts):
        if count >= data_column_count:
            return index

    return 0


# --- Header Detection ---


def detect_has_header(dataframe: pd.DataFrame) -> bool:
    """Detect if the first row is a header row.

    Heuristics:
    - Header rows typically have non-numeric values
    - Header rows often have common words (Date, Amount, etc.)
    - Data rows are typically more numeric

    Args:
        dataframe: DataFrame read without header assumption

    Returns:
        True if first row looks like headers
    """
    if dataframe.empty:
        return True

    first_row = dataframe.iloc[0]
    header_indicators = ["date", "datum", "amount", "betrag", "description", "verwendung", "name", "iban", "reference"]

    # Check if first row contains header-like text
    header_score = 0
    numeric_score = 0

    for value in first_row:
        value_str = str(value).lower().strip()

        # Check for header keywords
        for indicator in header_indicators:
            if indicator in value_str:
                header_score += 2
                break

        # Check if value looks numeric (data row indicator)
        try:
            # Try parsing as number (with German/English format)
            cleaned = value_str.replace(".", "").replace(",", ".").replace("€", "").replace("$", "").strip()
            if cleaned and cleaned.replace("-", "").replace("+", "").replace(".", "").isdigit():
                numeric_score += 1
        except Exception:
            pass

        # Check if value looks like a date (data row indicator)
        date_patterns = [r"\d{2}[./-]\d{2}[./-]\d{2,4}", r"\d{4}[./-]\d{2}[./-]\d{2}"]
        for pattern in date_patterns:
            if re.match(pattern, value_str):
                numeric_score += 1
                break

    # If header indicators dominate, it's a header
    return header_score > numeric_score


# --- Amount Format Detection ---


def detect_amount_format(values: list[str]) -> str:
    """Detect number format (German vs English) from sample values.

    German: 1.234,56 (period=thousands, comma=decimal)
    English: 1,234.56 (comma=thousands, period=decimal)

    Args:
        values: Sample amount values

    Returns:
        "german" or "english"
    """
    german_score = 0
    english_score = 0

    for value in values:
        value = str(value).strip().replace("€", "").replace("$", "").replace(" ", "")

        if not value or value == "nan":
            continue

        # Pattern: has comma before period → German (1.234,56)
        # Pattern: has period before comma → English (1,234.56)
        comma_pos = value.rfind(",")
        period_pos = value.rfind(".")

        if comma_pos > 0 and period_pos > 0:
            if comma_pos > period_pos:
                german_score += 1  # Comma is decimal separator
            else:
                english_score += 1  # Period is decimal separator
        elif comma_pos > 0 and period_pos < 0:
            # Only comma: could be German decimal (123,45) or English thousands (1,234)
            # Check if exactly 2 digits after comma → likely German decimal
            after_comma = value[comma_pos + 1 :]
            if len(after_comma) == 2 and after_comma.isdigit():
                german_score += 1
        elif period_pos > 0 and comma_pos < 0:
            # Only period: could be English decimal (123.45) or German thousands (1.234)
            # Check if exactly 2 digits after period → likely English decimal
            after_period = value[period_pos + 1 :]
            if len(after_period) == 2 and after_period.isdigit():
                english_score += 1

    # Default to english when scores are tied or unclear
    return "german" if german_score > english_score else "english"


# --- Date Format Detection ---

COMMON_DATE_FORMATS = [
    ("%Y-%m-%d", "unambiguous"),  # ISO: 2026-02-20
    ("%d.%m.%Y %H:%M:%S", "unambiguous"),  # German with time: 20.02.2026 14:30:00
    ("%d.%m.%Y", "unambiguous"),  # German: 20.02.2026
    ("%d.%m.%y", "unambiguous"),  # German short: 20.02.26
    ("%Y-%m-%d %H:%M:%S", "unambiguous"),  # ISO with time: 2026-02-20 14:30:00
    ("%d/%m/%Y", "ambiguous"),  # European: 20/02/2026 (DD/MM vs MM/DD)
    ("%d/%m/%y", "ambiguous"),  # European short: 20/02/26
    ("%m/%d/%Y", "ambiguous"),  # US: 02/20/2026 (could be DD/MM too)
    ("%m/%d/%y", "ambiguous"),  # US short: 02/20/26
    ("%Y/%m/%d", "unambiguous"),  # Asian: 2026/02/20
    ("%d-%m-%Y", "unambiguous"),  # European with dash: 20-02-2026
    ("%d-%m-%y", "unambiguous"),  # European short with dash: 20-02-26
]

# Long-form date formats with month names (English).
# These need locale-aware parsing — strptime %B only works for English names
# by default, so we handle German month names via _normalize_date_string().
LONG_DATE_FORMATS = [
    ("%d. %B %Y", "unambiguous"),  # Etsy: "31. January 2026"
    ("%B %d, %Y", "unambiguous"),  # US long: "January 31, 2026"
    ("%d %B %Y", "unambiguous"),  # UK long: "31 January 2026"
]


def _normalize_date_string(value: str) -> str:
    """Normalize date string with non-English month names to English for strptime.

    Uses dateutil.parser as fallback for locale-aware parsing.
    strptime %B only understands English month names, so we translate
    common German month names. dateutil handles the rest.
    """
    try:
        # dateutil.parser handles many languages and formats automatically
        from dateutil import parser as dateutil_parser

        parsed = dateutil_parser.parse(value, dayfirst=True)
        # Re-format to a standard English string that strptime can handle
        return parsed.strftime("%d. %B %Y")
    except (ValueError, ImportError, OverflowError):
        return value


def detect_date_format(values: list[str]) -> tuple[str | None, DateAmbiguity]:
    """Detect date format from sample values.

    Args:
        values: Sample date values

    Returns:
        Tuple of (strptime_format, ambiguity_status)
        If ambiguous, returns the format that worked but flags it
    """
    clean_values = [str(v).strip() for v in values if str(v).strip() and str(v).strip() != "nan"]

    if not clean_values:
        return None, DateAmbiguity.UNKNOWN

    format_scores: dict[str, int] = {}
    format_ambiguity: dict[str, str] = {}

    for date_format, ambiguity in COMMON_DATE_FORMATS:
        matches = 0
        for value in clean_values:
            try:
                datetime.strptime(value, date_format)
                matches += 1
            except ValueError:
                pass

        if matches > 0:
            format_scores[date_format] = matches
            format_ambiguity[date_format] = ambiguity

    # Also try long-form formats with month names (English + German)
    for date_format, ambiguity in LONG_DATE_FORMATS:
        matches = 0
        for value in clean_values:
            try:
                normalized = _normalize_date_string(value)
                datetime.strptime(normalized, date_format)
                matches += 1
            except ValueError:
                pass

        if matches > 0:
            format_scores[date_format] = matches
            format_ambiguity[date_format] = ambiguity

    if not format_scores:
        return None, DateAmbiguity.UNKNOWN

    # Pick the format with most matches
    best_format = max(format_scores, key=lambda f: format_scores[f])
    ambiguity_str = format_ambiguity[best_format]

    # Check for DD/MM vs MM/DD ambiguity
    # If values could be parsed by both formats, it's ambiguous
    dd_mm_formats = ["%d/%m/%Y", "%d/%m/%y"]
    mm_dd_formats = ["%m/%d/%Y", "%m/%d/%y"]

    if best_format in dd_mm_formats or best_format in mm_dd_formats:
        # Check if the alternative format also works for all values
        alt_formats = mm_dd_formats if best_format in dd_mm_formats else dd_mm_formats
        for alt_format in alt_formats:
            alt_matches = 0
            for value in clean_values:
                try:
                    datetime.strptime(value, alt_format)
                    alt_matches += 1
                except ValueError:
                    pass
            # If alternative format matches equally well, it's truly ambiguous
            if alt_matches == format_scores[best_format]:
                return best_format, DateAmbiguity.AMBIGUOUS

    ambiguity = DateAmbiguity.UNAMBIGUOUS if ambiguity_str == "unambiguous" else DateAmbiguity.AMBIGUOUS
    return best_format, ambiguity


# --- Main Detection Function ---


def detect_csv_options(content: bytes) -> DetectedCsvOptions:
    """Auto-detect CSV parsing options from raw content.

    Detects:
    - Encoding
    - Delimiter
    - Header presence
    - Skip rows (metadata rows before header)
    - Date format (with ambiguity flag)
    - Amount format (German vs English)
    - Column headers and sample values

    Args:
        content: Raw CSV bytes

    Returns:
        DetectedCsvOptions with all detected settings
    """
    # Step 1: Detect encoding
    encoding = detect_encoding(content)

    # Step 2: Decode content
    try:
        text_content = content.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        text_content = content.decode("utf-8", errors="replace")
        encoding = "utf-8"

    # Step 3: Detect delimiter
    delimiter = detect_delimiter(text_content)

    # Step 4: Detect metadata rows to skip
    skip_rows = detect_skip_rows(text_content, delimiter)

    # Step 5: Read CSV and detect header (after skipping metadata)
    try:
        dataframe_no_header = pd.read_csv(
            StringIO(text_content),
            sep=delimiter,
            header=None,
            skiprows=skip_rows,
            nrows=10,
            encoding=encoding,
            on_bad_lines="skip",
            dtype=str,
        )
    except Exception:
        # Fallback: try with utf-8
        dataframe_no_header = pd.read_csv(
            StringIO(text_content),
            sep=delimiter,
            header=None,
            skiprows=skip_rows,
            nrows=10,
            on_bad_lines="skip",
            dtype=str,
        )

    has_header = detect_has_header(dataframe_no_header)

    # Step 6: Read with proper header (after skipping metadata)
    try:
        dataframe = pd.read_csv(
            StringIO(text_content),
            sep=delimiter,
            header=0 if has_header else None,
            skiprows=skip_rows,
            nrows=20,
            encoding=encoding,
            on_bad_lines="skip",
            dtype=str,
        )
    except Exception:
        dataframe = dataframe_no_header
        has_header = False

    # Step 7: Extract column headers
    if has_header:
        column_headers = [str(col) for col in dataframe.columns.tolist()]
    else:
        column_headers = [f"Column_{i}" for i in range(len(dataframe.columns))]

    # Step 8: Extract sample values (first 5 non-empty values per column)
    sample_values: dict[str, list[str]] = {}
    for col in dataframe.columns:
        values = []
        for value in dataframe[col].dropna().head(5):
            value_string = str(value).strip()
            if value_string and value_string != "nan":
                values.append(value_string)
        col_name = str(col) if has_header else f"Column_{dataframe.columns.get_loc(col)}"
        sample_values[col_name] = values

    # Step 9: Detect date format (try to find a date-looking column)
    date_format = None
    date_ambiguity = DateAmbiguity.UNKNOWN

    date_column_hints = ["date", "datum", "buchung", "valuta", "wertstellung"]
    for col_name, values in sample_values.items():
        # Check if column name suggests dates
        col_lower = col_name.lower()
        if any(hint in col_lower for hint in date_column_hints) or (values and re.match(r"\d", values[0])):
            detected_format, detected_ambiguity = detect_date_format(values)
            if detected_format:
                date_format = detected_format
                date_ambiguity = detected_ambiguity
                break

    # Step 10: Detect amount format (try to find an amount-looking column)
    amount_format = "english"  # Default

    amount_column_hints = ["amount", "betrag", "summe", "total", "value", "saldo", "credit", "debit", "haben", "soll"]
    for col_name, values in sample_values.items():
        col_lower = col_name.lower()
        if any(hint in col_lower for hint in amount_column_hints):
            amount_format = detect_amount_format(values)
            break

    # Step 11: Suggest column assignments from sample values
    suggested = suggest_columns(column_headers, sample_values) if has_header else None

    return DetectedCsvOptions(
        delimiter=delimiter,
        encoding=encoding,
        has_header=has_header,
        skip_rows=skip_rows,
        date_format=date_format,
        date_ambiguity=date_ambiguity,
        amount_format=amount_format,
        column_headers=column_headers,
        sample_values=sample_values,
        suggested_columns=suggested,
    )


def compute_unique_values(
    content: bytes,
    options: DetectedCsvOptions,
    max_cardinality: int = 50,
) -> dict[str, list[str]]:
    """Compute unique values per column for filter dropdowns.

    Reads the full CSV (not just sample rows) to find all unique values.
    Only includes columns with reasonable cardinality (2..max_cardinality unique values).

    Args:
        content: Raw CSV bytes
        options: Detected CSV options from detect_csv_options()
        max_cardinality: Maximum unique values per column (higher = likely not categorical)

    Returns:
        {column_name: sorted list of unique values} for categorical columns
    """
    try:
        text_content = content.decode(options.encoding)
    except (UnicodeDecodeError, LookupError):
        text_content = content.decode("utf-8", errors="replace")

    try:
        dataframe = pd.read_csv(
            StringIO(text_content),
            sep=options.delimiter,
            header=0 if options.has_header else None,
            skiprows=options.skip_rows,
            on_bad_lines="skip",
            dtype=str,
        )
    except Exception:
        return {}

    unique_values: dict[str, list[str]] = {}
    for col in dataframe.columns:
        col_name = str(col)
        values = dataframe[col].dropna().astype(str).str.strip()
        unique = sorted(values.unique().tolist())
        if 1 < len(unique) <= max_cardinality:
            unique_values[col_name] = unique

    return unique_values


# --- Column Suggestion (content-based) ---


def _looks_like_date(values: list[str]) -> bool:
    """Check if sample values look like dates."""
    if not values:
        return False
    date_pattern = re.compile(r"^\d{1,4}[./-]\d{1,2}[./-]\d{2,4}")
    matches = sum(1 for v in values if date_pattern.match(v.strip()))
    return matches >= len(values) * 0.8


def _looks_like_amount(values: list[str]) -> bool:
    """Check if sample values look like monetary amounts."""
    if not values:
        return False
    # Amounts: optional sign, optional currency, digits with separators
    amount_pattern = re.compile(r"^[€$£]?\s*[+-]?\s*\d[\d.,\s]*\d?$|^[+-]?\s*[€$£]?\s*\d[\d.,\s]*\d?$|^[+-]?\d+([.,]\d+)?$")
    matches = sum(1 for v in values if amount_pattern.match(v.strip().replace("\xa0", "")))
    return matches >= len(values) * 0.8


def _looks_like_freetext(values: list[str]) -> bool:
    """Check if sample values look like varied free text (names, descriptions).

    Filters out:
    - Enum-like columns (Status, Type) — low uniqueness
    - Code-like columns (BIC, IBAN, UUID) — no spaces, short, alphanumeric patterns
    - Single-word status fields — short average length
    """
    if not values:
        return False
    clean = [v.strip() for v in values if v.strip() and v.strip() != "nan"]
    if not clean:
        return False

    # Must contain letters
    has_letters = sum(1 for v in clean if any(c.isalpha() for c in v))
    if has_letters < len(clean) * 0.6:
        return False

    # Must have varied values (not enum-like "Gebucht", "Gebucht", "Gebucht")
    unique_ratio = len(set(clean)) / len(clean) if clean else 0
    if unique_ratio < 0.4:
        return False

    # Must have reasonable average length (not single-word status fields)
    average_length = sum(len(v) for v in clean) / len(clean)
    if average_length < 5:
        return False

    # At least some values must contain spaces (filters out codes: BIC, IBAN, UUID)
    has_spaces = sum(1 for v in clean if " " in v)
    if has_spaces < len(clean) * 0.3:
        return False

    return True


def suggest_columns(
    column_headers: list[str],
    sample_values: dict[str, list[str]],
) -> SuggestedColumns:
    """Suggest column assignments purely by analyzing sample values.

    Detects columns by content type:
    - Date columns: values match date patterns
    - Amount columns: values are numeric with optional sign/currency
    - Text columns: varied free text with reasonable length

    When multiple candidates exist, picks the best by scoring:
    - Amount: prefers columns with mixed positive/negative values
    - Text (counterparty): shorter average length (names)
    - Text (description): longer average length (descriptions, memos)

    Args:
        column_headers: List of column header strings
        sample_values: column_name → list of sample value strings

    Returns:
        SuggestedColumns with best-guess assignments
    """
    date_columns: list[str] = []
    amount_columns: list[str] = []
    text_columns: list[str] = []

    for header in column_headers:
        values = sample_values.get(header, [])
        clean_values = [v for v in values if v and v.strip() and v.strip() != "nan"]

        if _looks_like_date(clean_values):
            date_columns.append(header)
        elif _looks_like_amount(clean_values):
            amount_columns.append(header)
        elif _looks_like_freetext(clean_values):
            text_columns.append(header)

    # Pick best amount column: prefer one with mixed signs (positive + negative)
    suggested_amount: str | None = None
    if amount_columns:
        best_amount = amount_columns[0]
        best_sign_score = 0
        for col in amount_columns:
            values = sample_values.get(col, [])
            has_positive = any(not v.strip().startswith("-") for v in values if v.strip())
            has_negative = any(v.strip().startswith("-") for v in values if v.strip())
            sign_score = (1 if has_positive else 0) + (1 if has_negative else 0)
            if sign_score > best_sign_score:
                best_sign_score = sign_score
                best_amount = col
        suggested_amount = best_amount

    # Sort text columns by average length to distinguish counterparty (shorter) from description (longer)
    def _average_length(col: str) -> float:
        values = sample_values.get(col, [])
        clean = [v for v in values if v.strip() and v.strip() != "nan"]
        return sum(len(v) for v in clean) / len(clean) if clean else 0

    text_columns.sort(key=_average_length)

    # Counterparty = shorter text, description = longer text
    suggested_counterparty = text_columns[0] if text_columns else None
    suggested_description = text_columns[-1] if len(text_columns) >= 2 else None
    # If only one text column, don't assign it to both
    if suggested_counterparty == suggested_description:
        suggested_description = None

    return SuggestedColumns(
        column_date=date_columns[0] if date_columns else None,
        column_amount=suggested_amount,
        column_counterparty=suggested_counterparty,
        column_description=suggested_description,
    )


# --- Amount Parsing ---


def parse_german_amount(value: str) -> Decimal:
    """Parse German-formatted amount (1.234,56 or -1.234,56).

    Args:
        value: Amount string in German format

    Returns:
        Decimal amount

    Raises:
        ValueError: If amount cannot be parsed
    """
    cleaned = sanitize_cell_value(value)
    cleaned = cleaned.replace("€", "").replace("$", "").replace("£", "").replace(" ", "").strip()

    if not cleaned:
        raise ValueError("Empty amount")

    # German format: 1.234,56 → remove thousands separator (.), replace decimal (,) with (.)
    cleaned = cleaned.replace(".", "").replace(",", ".")

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Cannot parse German amount: {value}") from exc


def parse_english_amount(value: str) -> Decimal:
    """Parse English-formatted amount (1,234.56 or -1,234.56).

    Also handles currency-prefixed formats like -€1.24 or €23.40.

    Args:
        value: Amount string in English format

    Returns:
        Decimal amount

    Raises:
        ValueError: If amount cannot be parsed
    """
    cleaned = sanitize_cell_value(value)
    # Handle currency symbols anywhere in the string (e.g., -€1.24)
    cleaned = cleaned.replace("$", "").replace("€", "").replace("£", "").replace(" ", "").strip()

    if not cleaned:
        raise ValueError("Empty amount")

    # English format: 1,234.56 → remove thousands separator (,)
    cleaned = cleaned.replace(",", "")

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Cannot parse English amount: {value}") from exc


_TWO_PLACES = Decimal("0.01")


def parse_amount_value(value: str, amount_format: str) -> Decimal:
    """Parse amount string according to specified format.

    Always quantizes to 2 decimal places for consistent output
    regardless of input format (German/English).

    Args:
        value: Amount string
        amount_format: "german" or "english"

    Returns:
        Decimal amount quantized to 2 decimal places
    """
    if amount_format == "german":
        return parse_german_amount(value).quantize(_TWO_PLACES)
    return parse_english_amount(value).quantize(_TWO_PLACES)


# --- Date Parsing ---


def parse_date_value(value: str, date_format: str) -> date:
    """Parse date string according to format.

    Handles German month names by normalizing to English before strptime.

    Args:
        value: Date string
        date_format: strptime format string

    Returns:
        Parsed date

    Raises:
        ValueError: If date cannot be parsed
    """
    cleaned = sanitize_cell_value(value)

    # For long-form formats with %B, normalize German month names to English
    if "%B" in date_format:
        cleaned = _normalize_date_string(cleaned)

    try:
        return datetime.strptime(cleaned, date_format).date()
    except ValueError as exc:
        raise ValueError(f"Cannot parse date '{value}' with format '{date_format}'") from exc


# --- Main Parsing Function ---


def parse_csv_with_mapping(content: bytes, mapping: CsvMappingLike) -> GenericParseResult:
    """Parse CSV content using user-defined column mapping.

    Args:
        content: Raw CSV bytes
        mapping: CsvMappingProfile with column assignments and parsing options

    Returns:
        GenericParseResult with parsed rows and any errors
    """
    # Decode content
    try:
        text_content = content.decode(mapping.encoding)
    except (UnicodeDecodeError, LookupError):
        text_content = content.decode("utf-8", errors="replace")

    # Read CSV with mapping options
    try:
        dataframe = pd.read_csv(
            StringIO(text_content),
            sep=mapping.delimiter,
            header=0 if mapping.has_header else None,
            skiprows=mapping.skip_rows,
            encoding=mapping.encoding,
            on_bad_lines="skip",
            dtype=str,
        )
    except Exception as exc:
        raise GenericCsvParseError(f"Failed to read CSV: {exc}") from exc

    parsed_rows: list[ParsedRow] = []
    errors: list[str] = []
    filtered_count = 0

    # Apply row-level filter if configured
    filter_column = getattr(mapping, "column_filter", None)
    filter_values = getattr(mapping, "filter_include_values", None)

    if filter_column and filter_values and filter_column in dataframe.columns:
        total_before = len(dataframe)
        dataframe = dataframe[dataframe[filter_column].astype(str).str.strip().isin(filter_values)]
        filtered_count = total_before - len(dataframe)

    # Determine amount format (default to english if not specified)
    amount_format = mapping.amount_format or "english"

    # Check which columns are mapped (marketplace may only have reference)
    has_date = bool(mapping.column_date and mapping.column_date in dataframe.columns)
    has_amount = bool(mapping.column_amount and mapping.column_amount in dataframe.columns)
    has_counterparty = bool(mapping.column_counterparty and mapping.column_counterparty in dataframe.columns)
    has_description = bool(mapping.column_description and mapping.column_description in dataframe.columns)
    has_reference = bool(mapping.column_reference and mapping.column_reference in dataframe.columns)

    # Date format required only if date column is mapped
    if has_date and not mapping.date_format:
        raise GenericCsvParseError("Date format is required when date column is mapped")
    date_format = mapping.date_format

    for row_index, (_index_label, row) in enumerate(dataframe.iterrows()):
        try:
            # Parse date (optional)
            parsed_date: date | None = None
            if has_date and date_format:
                date_value = str(row[mapping.column_date]).strip()
                if date_value and date_value != "nan" and date_value != "--":
                    parsed_date = parse_date_value(date_value, date_format)

            # Parse amount (optional)
            amount = None
            if has_amount:
                amount_str = str(row[mapping.column_amount]).strip()
                if amount_str and amount_str != "nan" and amount_str != "--":
                    amount = parse_amount_value(amount_str, amount_format)

            # Parse counterparty (optional)
            counterparty = None
            if has_counterparty:
                counterparty = sanitize_cell_value(str(row[mapping.column_counterparty]))
                if counterparty == "nan" or not counterparty:
                    counterparty = None

            # Parse description (optional)
            description = None
            if has_description:
                description = sanitize_cell_value(str(row[mapping.column_description]))
                if description == "nan":
                    description = None

            # Parse reference (optional)
            reference = None
            if has_reference:
                ref_value = str(row[mapping.column_reference]).strip()
                if ref_value and ref_value != "nan":
                    reference = sanitize_cell_value(ref_value)

            parsed_rows.append(
                ParsedRow(
                    date=parsed_date,
                    amount=amount,
                    counterparty=counterparty,
                    description=description,
                    source_reference=reference,
                    raw_row=row.to_dict(),
                )
            )

        except Exception as exc:
            errors.append(f"Row {row_index + 1}: {exc}")

    return GenericParseResult(rows=parsed_rows, errors=errors, filtered_count=filtered_count, kept_count=len(parsed_rows))


# --- Import Hash Computation ---


def compute_import_hash(source_config_id: str, transaction_date: date, amount: Decimal, counterparty: str) -> str:
    """Compute SHA-256 hash for generic CSV duplicate detection.

    Normalizes fields and delegates to shared csv_utils.compute_import_hash().
    """
    return _shared_compute_import_hash(
        source_config_id,
        transaction_date.isoformat(),
        str(amount.quantize(Decimal("0.01"))),
        counterparty.strip().lower(),
    )
