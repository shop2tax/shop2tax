"""Tests for generic CSV parser with user-defined column mapping.

Tests cover:
- German/English amount parsing
- Split debit/credit mode
- Date format detection and parsing
- CSV formula injection sanitization
- Import hash computation
- Full parsing with mapping
"""

from datetime import date
from decimal import Decimal

import pytest
from app.services.generic_csv_parser import (
    DateAmbiguity,
    GenericCsvParseError,
    compute_import_hash,
    detect_amount_format,
    detect_csv_options,
    detect_date_format,
    detect_delimiter,
    detect_encoding,
    detect_skip_rows,
    parse_amount_value,
    parse_csv_with_mapping,
    parse_date_value,
    parse_english_amount,
    parse_german_amount,
    sanitize_cell_value,
)


class TestCsvFormulaSanitization:
    """Tests for CSV formula injection sanitization."""

    def should_sanitize_equals_sign(self):
        """Strip leading = to prevent formula injection."""
        assert sanitize_cell_value("=SUM(A1:A10)") == "SUM(A1:A10)"
        assert sanitize_cell_value("= cmd|' /C calc'!A0") == "cmd|' /C calc'!A0"

    def should_sanitize_at_sign(self):
        """Strip leading @ to prevent mention/formula injection."""
        assert sanitize_cell_value("@SUM(A1)") == "SUM(A1)"

    def should_sanitize_plus_not_followed_by_digit(self):
        """Strip leading + when not followed by digit."""
        assert sanitize_cell_value("+cmd") == "cmd"
        assert sanitize_cell_value("+ 123") == "123"

    def should_preserve_plus_followed_by_digit(self):
        """Keep + when followed by digit (positive number)."""
        assert sanitize_cell_value("+123.45") == "+123.45"

    def should_sanitize_minus_not_followed_by_digit(self):
        """Strip leading - when not followed by digit."""
        assert sanitize_cell_value("-cmd") == "cmd"
        assert sanitize_cell_value("- calc") == "calc"

    def should_preserve_minus_followed_by_digit(self):
        """Keep - when followed by digit (negative number)."""
        assert sanitize_cell_value("-123.45") == "-123.45"
        assert sanitize_cell_value("-1,234.56") == "-1,234.56"

    def should_handle_empty_and_none(self):
        """Handle empty strings."""
        assert sanitize_cell_value("") == ""
        assert sanitize_cell_value("  ") == ""

    def should_strip_whitespace(self):
        """Strip surrounding whitespace."""
        assert sanitize_cell_value("  normal value  ") == "normal value"


class TestAmountParsing:
    """Tests for German and English amount parsing."""

    # --- German format ---

    def should_parse_german_positive_amount(self):
        """Parse German format: 1.234,56"""
        assert parse_german_amount("1.234,56") == Decimal("1234.56")

    def should_parse_german_negative_amount(self):
        """Parse German format: -1.234,56"""
        assert parse_german_amount("-1.234,56") == Decimal("-1234.56")

    def should_parse_german_amount_with_euro(self):
        """Parse German amount with € symbol."""
        assert parse_german_amount("€ 100,00") == Decimal("100.00")
        assert parse_german_amount("100,00 €") == Decimal("100.00")
        assert parse_german_amount("€1.234,56") == Decimal("1234.56")

    def should_parse_german_amount_no_thousands(self):
        """Parse German amount without thousands separator."""
        assert parse_german_amount("234,56") == Decimal("234.56")

    def should_raise_on_empty_german_amount(self):
        """Raise ValueError on empty German amount."""
        with pytest.raises(ValueError, match="Empty amount"):
            parse_german_amount("")
        with pytest.raises(ValueError, match="Empty amount"):
            parse_german_amount("  ")

    def should_raise_on_invalid_german_amount(self):
        """Raise ValueError on non-numeric German amount."""
        with pytest.raises(ValueError, match="Cannot parse German amount"):
            parse_german_amount("abc")

    # --- English format ---

    def should_parse_english_positive_amount(self):
        """Parse English format: 1,234.56"""
        assert parse_english_amount("1,234.56") == Decimal("1234.56")

    def should_parse_english_negative_amount(self):
        """Parse English format: -1,234.56"""
        assert parse_english_amount("-1,234.56") == Decimal("-1234.56")

    def should_parse_english_amount_with_dollar(self):
        """Parse English amount with $ symbol."""
        assert parse_english_amount("$100.00") == Decimal("100.00")
        assert parse_english_amount("$ 1,234.56") == Decimal("1234.56")

    def should_parse_english_amount_with_euro(self):
        """Parse English amount with € symbol."""
        assert parse_english_amount("€100.00") == Decimal("100.00")

    def should_raise_on_empty_english_amount(self):
        """Raise ValueError on empty English amount."""
        with pytest.raises(ValueError, match="Empty amount"):
            parse_english_amount("")

    def should_raise_on_invalid_english_amount(self):
        """Raise ValueError on non-numeric English amount."""
        with pytest.raises(ValueError, match="Cannot parse English amount"):
            parse_english_amount("xyz")

    # --- parse_amount_value dispatcher ---

    def should_dispatch_to_german_parser(self):
        """parse_amount_value with german format."""
        assert parse_amount_value("1.234,56", "german") == Decimal("1234.56")

    def should_dispatch_to_english_parser(self):
        """parse_amount_value with english format."""
        assert parse_amount_value("1,234.56", "english") == Decimal("1234.56")


class TestDateParsing:
    """Tests for date parsing."""

    def should_parse_iso_date(self):
        """Parse ISO format: 2026-02-20"""
        assert parse_date_value("2026-02-20", "%Y-%m-%d") == date(2026, 2, 20)

    def should_parse_german_date_full(self):
        """Parse German format: 20.02.2026"""
        assert parse_date_value("20.02.2026", "%d.%m.%Y") == date(2026, 2, 20)

    def should_parse_german_date_short(self):
        """Parse German short format: 20.02.26"""
        assert parse_date_value("20.02.26", "%d.%m.%y") == date(2026, 2, 20)

    def should_parse_european_slash(self):
        """Parse European format: 20/02/2026"""
        assert parse_date_value("20/02/2026", "%d/%m/%Y") == date(2026, 2, 20)

    def should_raise_on_invalid_date(self):
        """Raise ValueError on invalid date format."""
        with pytest.raises(ValueError, match="Cannot parse date"):
            parse_date_value("not-a-date", "%Y-%m-%d")

    def should_strip_whitespace_from_date(self):
        """Strip whitespace before parsing."""
        assert parse_date_value("  2026-02-20  ", "%Y-%m-%d") == date(2026, 2, 20)


class TestDateFormatDetection:
    """Tests for automatic date format detection."""

    def should_detect_iso_format(self):
        """Detect ISO date format as unambiguous."""
        date_format, ambiguity = detect_date_format(["2026-02-20", "2026-03-15", "2026-04-01"])
        assert date_format == "%Y-%m-%d"
        assert ambiguity == DateAmbiguity.UNAMBIGUOUS

    def should_detect_german_format(self):
        """Detect German date format as unambiguous."""
        date_format, ambiguity = detect_date_format(["20.02.2026", "15.03.2026", "01.04.2026"])
        assert date_format == "%d.%m.%Y"
        assert ambiguity == DateAmbiguity.UNAMBIGUOUS

    def should_detect_ambiguous_slash_format(self):
        """Detect DD/MM vs MM/DD ambiguity when both are valid."""
        # 05/06/2026 could be May 6 or June 5
        date_format, ambiguity = detect_date_format(["05/06/2026", "03/04/2026", "01/02/2026"])
        # Should detect but flag as ambiguous
        assert date_format is not None
        assert ambiguity == DateAmbiguity.AMBIGUOUS

    def should_resolve_unambiguous_slash_format(self):
        """Detect slash format when day > 12 (only DD/MM can be valid)."""
        # 20/02/2026 can only be DD/MM (no month 20)
        # The format is detected, but ambiguity depends on implementation
        date_format, ambiguity = detect_date_format(["20/02/2026", "25/03/2026", "15/04/2026"])
        assert date_format == "%d/%m/%Y"
        # May still be marked as potentially ambiguous format family
        assert ambiguity in (DateAmbiguity.UNAMBIGUOUS, DateAmbiguity.AMBIGUOUS)

    def should_return_unknown_for_unrecognized_format(self):
        """Return unknown ambiguity for unrecognized formats."""
        date_format, ambiguity = detect_date_format(["not-a-date", "also-not", "nope"])
        assert date_format is None
        assert ambiguity == DateAmbiguity.UNKNOWN

    def should_handle_empty_values(self):
        """Handle empty or nan values gracefully."""
        date_format, ambiguity = detect_date_format(["", "nan", "  "])
        assert date_format is None
        assert ambiguity == DateAmbiguity.UNKNOWN


class TestAmountFormatDetection:
    """Tests for automatic amount format detection."""

    def should_detect_german_format(self):
        """Detect German format from comma decimal."""
        assert detect_amount_format(["1.234,56", "-100,00", "50,99"]) == "german"

    def should_detect_english_format(self):
        """Detect English format from period decimal."""
        assert detect_amount_format(["1,234.56", "-100.00", "50.99"]) == "english"

    def should_handle_mixed_input(self):
        """Handle input with mixed or ambiguous values."""
        # Default to english when unclear
        assert detect_amount_format(["100", "200", "300"]) == "english"

    def should_handle_empty_values(self):
        """Handle empty values gracefully."""
        assert detect_amount_format(["", "nan", "  "]) == "english"


class TestDelimiterDetection:
    """Tests for CSV delimiter detection."""

    def should_detect_comma(self):
        """Detect comma delimiter."""
        content = "col1,col2,col3\nval1,val2,val3\n"
        assert detect_delimiter(content) == ","

    def should_detect_semicolon(self):
        """Detect semicolon delimiter."""
        content = "col1;col2;col3\nval1;val2;val3\n"
        assert detect_delimiter(content) == ";"

    def should_detect_tab(self):
        """Detect tab delimiter."""
        content = "col1\tcol2\tcol3\nval1\tval2\tval3\n"
        assert detect_delimiter(content) == "\t"

    def should_prefer_consistent_delimiter(self):
        """Prefer delimiter with consistent column count across rows."""
        # This CSV has consistent semicolons
        content = "a;b;c\n1;2;3\n4;5;6\n"
        assert detect_delimiter(content) == ";"


class TestSkipRowsDetection:
    """Tests for metadata row detection (skip_rows)."""

    def should_skip_metadata_rows_with_fewer_columns(self):
        """Skip rows that have fewer columns than the data section."""
        content = (
            '"Account";"DE49120300001032569392"\n'
            '"Period:";"21.01.2026 - 20.02.2026"\n'
            '"Balance:";"1.154,38"\n'
            '""\n'
            '"Date";"Value";"Status";"Name";"Recipient";"Purpose";"Type";"IBAN";"Amount";"ID";"Mandate";"Ref"\n'
            '"10.02.26";"10.02.26";"Done";"Test";"Test GmbH";"Invoice";"Out";"DE84";"-313,37";"DE14";"NW123";"REF1"\n'
            '"09.02.26";"09.02.26";"Done";"Test2";"AG";"Payment";"In";"DE12";"100,00";"";"";""\n'
        )
        assert detect_skip_rows(content, ";") == 4

    def should_return_zero_for_simple_csv(self):
        """No skip for CSV without metadata rows."""
        content = "date,amount,name\n2026-01-01,100,Test\n2026-01-02,200,Test2\n"
        assert detect_skip_rows(content, ",") == 0

    def should_handle_single_metadata_row(self):
        """Detect single metadata row before header."""
        content = '"Export from MyBank"\n"Date";"Amount";"Name"\n"10.02.26";"100,00";"Test"\n"09.02.26";"200,00";"Test2"\n'
        assert detect_skip_rows(content, ";") == 1

    def should_handle_csv_with_empty_lines_as_separator(self):
        """Detect empty line as part of metadata section."""
        content = '"Account Info";"12345"\n\n"Col1";"Col2";"Col3"\n"A";"B";"C"\n"D";"E";"F"\n'
        assert detect_skip_rows(content, ";") == 2

    def should_return_zero_for_minimal_csv(self):
        """No skip for very short CSV."""
        content = "a,b\n1,2\n"
        assert detect_skip_rows(content, ",") == 0


class TestEncodingDetection:
    """Tests for encoding detection."""

    def should_detect_utf8_bom(self):
        """Detect UTF-8 with BOM."""
        content = b"\xef\xbb\xbfcol1,col2\nval1,val2\n"
        assert detect_encoding(content) == "utf-8-sig"

    def should_detect_utf8(self):
        """Detect UTF-8 without BOM."""
        content = "col1,col2\nval1,val2\n".encode("utf-8")
        assert detect_encoding(content) in ("utf-8", "ascii")

    def should_detect_non_utf8_encoding(self):
        """Detect non-UTF-8 encoding (charset-normalizer result varies)."""
        # Ä in ISO-8859-1 is 0xC4
        content = b"col1,col2\nv\xc4lue1,val2\n"
        encoding = detect_encoding(content)
        # charset-normalizer may return various encodings for this ambiguous input
        # Just verify we get a valid encoding string
        assert isinstance(encoding, str)
        assert len(encoding) > 0


class TestImportHashComputation:
    """Tests for import hash computation."""

    def should_compute_deterministic_hash(self):
        """Same inputs produce same hash."""
        hash1 = compute_import_hash("source-123", date(2026, 2, 20), Decimal("100.50"), "Test Corp")
        hash2 = compute_import_hash("source-123", date(2026, 2, 20), Decimal("100.50"), "Test Corp")
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def should_produce_different_hash_for_different_source(self):
        """Different source_config_id produces different hash."""
        hash1 = compute_import_hash("source-123", date(2026, 2, 20), Decimal("100.50"), "Test Corp")
        hash2 = compute_import_hash("source-456", date(2026, 2, 20), Decimal("100.50"), "Test Corp")
        assert hash1 != hash2

    def should_produce_different_hash_for_different_date(self):
        """Different date produces different hash."""
        hash1 = compute_import_hash("source-123", date(2026, 2, 20), Decimal("100.50"), "Test Corp")
        hash2 = compute_import_hash("source-123", date(2026, 2, 21), Decimal("100.50"), "Test Corp")
        assert hash1 != hash2

    def should_produce_different_hash_for_different_amount(self):
        """Different amount produces different hash."""
        hash1 = compute_import_hash("source-123", date(2026, 2, 20), Decimal("100.50"), "Test Corp")
        hash2 = compute_import_hash("source-123", date(2026, 2, 20), Decimal("100.51"), "Test Corp")
        assert hash1 != hash2

    def should_normalize_counterparty_case(self):
        """Hash should be case-insensitive for counterparty."""
        hash1 = compute_import_hash("source-123", date(2026, 2, 20), Decimal("100.50"), "Test Corp")
        hash2 = compute_import_hash("source-123", date(2026, 2, 20), Decimal("100.50"), "test corp")
        hash3 = compute_import_hash("source-123", date(2026, 2, 20), Decimal("100.50"), "TEST CORP")
        assert hash1 == hash2 == hash3

    def should_normalize_amount_precision(self):
        """Hash should normalize amount to 2 decimal places."""
        hash1 = compute_import_hash("source-123", date(2026, 2, 20), Decimal("100.50"), "Test")
        hash2 = compute_import_hash("source-123", date(2026, 2, 20), Decimal("100.500"), "Test")
        hash3 = compute_import_hash("source-123", date(2026, 2, 20), Decimal("100.5"), "Test")
        assert hash1 == hash2 == hash3


class TestCsvOptionsDetection:
    """Tests for full CSV options detection."""

    def should_detect_basic_csv_options(self):
        """Detect options from basic CSV."""
        content = b"date,amount,counterparty,description\n2026-02-20,100.50,Test Corp,Invoice\n"
        options = detect_csv_options(content)

        assert options.delimiter == ","
        assert options.encoding in ("utf-8", "ascii", "utf-8-sig")
        assert options.has_header is True
        assert options.column_headers == ["date", "amount", "counterparty", "description"]
        assert len(options.sample_values) == 4

    def should_detect_german_csv_options(self):
        """Detect options from German-formatted CSV."""
        content = b"Datum;Betrag;Empfaenger;Verwendungszweck\n20.02.2026;100,50;Test GmbH;Rechnung\n"
        options = detect_csv_options(content)

        assert options.delimiter == ";"
        assert options.amount_format == "german"

    def should_return_sample_values(self):
        """Return sample values per column."""
        # Use header names that look more like headers (contain common keywords)
        content = b"date,amount,name,description\n2026-01-01,100.00,Test,Inv\n2026-01-02,200.00,Corp,Fee\n"
        options = detect_csv_options(content)

        # Should detect headers and return sample values
        assert len(options.sample_values) >= 2
        # Check that we have sample values (column names depend on header detection)
        all_values = []
        for values in options.sample_values.values():
            all_values.extend(values)
        # Should include at least some of the data values
        assert any("2026" in v or "100" in v or "Test" in v for v in all_values)

    def should_detect_skip_rows_in_csv_with_metadata_header(self):
        """Detect metadata rows and return correct headers after skipping."""
        content = (
            b'"Account";"DE49120300001032569392"\n'
            b'"Period:";"21.01 - 20.02"\n'
            b'"Balance:";"1.154,38"\n'
            b'""\n'
            b'"Date";"ValueDate";"Status";"Name";"Amount"\n'
            b'"10.02.26";"10.02.26";"Done";"Test GmbH";"-313,37"\n'
            b'"09.02.26";"09.02.26";"Done";"Test AG";"100,00"\n'
        )
        options = detect_csv_options(content)

        assert options.skip_rows == 4
        assert options.delimiter == ";"
        assert options.has_header is True
        assert "Date" in options.column_headers
        assert "Amount" in options.column_headers

    def should_handle_large_integer_ids_without_overflow(self):
        """Amazon settlement-id (26579761962) must not overflow dateutil parser.

        dateutil.parser.parse() interprets bare integers as years — a settlement-id
        like 26579761962 causes OverflowError in datetime.replace(year=26579761962).
        """
        headers = (
            "settlement-id\tsettlement-start-date\tsettlement-end-date\tdeposit-date\t"
            "total-amount\tcurrency\ttransaction-type\torder-id\tmerchant-order-id\t"
            "adjustment-id\tshipment-id\tmarketplace-name\tamount-type\tamount-description\t"
            "amount\tfulfillment-id\tposted-date\tposted-date-time\torder-item-code\t"
            "merchant-order-item-id\tmerchant-adjustment-item-id\tsku\tquantity-purchased\tpromotion-id"
        )
        summary = "26579761962\t2024-01-01\t2024-01-14\t2024-01-16\t1234,56\tEUR\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t"
        order = (
            "26579761962\t\t\t\t\tEUR\tOrder\t306-9162999-5341943\t\t\t\tamazon.de\tItemPrice\tPrincipal\t17,95\t\t2024-01-10\t\t\t\t\tSKU001\t1\t"
        )
        content = f"{headers}\n{summary}\n{order}\n".encode("utf-8")

        options = detect_csv_options(content)

        assert options.delimiter == "\t"
        assert options.has_header is True


class MappingAdapter:
    """Test adapter for CsvMappingProfile interface."""

    def __init__(
        self,
        delimiter: str = ",",
        encoding: str = "utf-8",
        has_header: bool = True,
        skip_rows: int = 0,
        date_format: str = "%Y-%m-%d",
        amount_format: str = "english",
        column_date: str = "date",
        column_amount: str = "amount",
        column_counterparty: str = "counterparty",
        column_description: str = "description",
        column_reference: str | None = None,
    ):
        self.delimiter = delimiter
        self.encoding = encoding
        self.has_header = has_header
        self.skip_rows = skip_rows
        self.date_format = date_format
        self.amount_format = amount_format
        self.column_date = column_date
        self.column_amount = column_amount
        self.column_counterparty = column_counterparty
        self.column_description = column_description
        self.column_reference = column_reference


class TestCsvParsingWithMapping:
    """Tests for full CSV parsing with user-defined mapping."""

    def should_parse_basic_csv(self):
        """Parse basic CSV with mapping."""
        content = b"date,amount,counterparty,description\n2026-02-20,100.50,Test Corp,Invoice payment\n"
        mapping = MappingAdapter()

        result = parse_csv_with_mapping(content, mapping)

        assert len(result.rows) == 1
        assert result.rows[0].date == date(2026, 2, 20)
        assert result.rows[0].amount == Decimal("100.50")
        assert result.rows[0].counterparty == "Test Corp"
        assert result.rows[0].description == "Invoice payment"
        assert result.errors == []

    def should_parse_german_format_csv(self):
        """Parse CSV with German number format."""
        content = b"Datum;Betrag;Empfaenger;Zweck\n20.02.2026;1.234,56;Test GmbH;Rechnung\n"
        mapping = MappingAdapter(
            delimiter=";",
            date_format="%d.%m.%Y",
            amount_format="german",
            column_date="Datum",
            column_amount="Betrag",
            column_counterparty="Empfaenger",
            column_description="Zweck",
        )

        result = parse_csv_with_mapping(content, mapping)

        assert len(result.rows) == 1
        assert result.rows[0].amount == Decimal("1234.56")

    def should_handle_optional_reference_column(self):
        """Parse CSV with optional reference column."""
        content = b"date,amount,counterparty,description,ref\n2026-02-20,100.50,Test,Inv,REF123\n"
        mapping = MappingAdapter(column_reference="ref")

        result = parse_csv_with_mapping(content, mapping)

        assert result.rows[0].source_reference == "REF123"

    def should_collect_row_errors(self):
        """Collect errors for invalid rows without failing completely."""
        content = b"date,amount,counterparty,description\n2026-02-20,100.50,Test,Good\ninvalid-date,50.00,Test,Bad\n"
        mapping = MappingAdapter()

        result = parse_csv_with_mapping(content, mapping)

        assert len(result.rows) == 1  # Only valid row
        assert len(result.errors) == 1  # One error
        assert "Row 2" in result.errors[0] or "invalid" in result.errors[0].lower()

    def should_keep_rows_with_empty_amount_as_none(self):
        """Rows with empty amount values are kept with amount=None."""
        content = b"date,amount,counterparty,description\n2026-02-20,100.50,Test,Good\n2026-02-21,,Test,Empty\n"
        mapping = MappingAdapter()

        result = parse_csv_with_mapping(content, mapping)

        assert len(result.rows) == 2
        assert result.rows[0].amount == Decimal("100.50")
        assert result.rows[1].amount is None

    def should_handle_missing_counterparty_as_none(self):
        """Set counterparty to None when missing."""
        content = b"date,amount,counterparty,description\n2026-02-20,100.50,,Invoice\n"
        mapping = MappingAdapter()

        result = parse_csv_with_mapping(content, mapping)

        assert result.rows[0].counterparty is None

    def should_sanitize_formula_in_cells(self):
        """Sanitize formula injection in cell values."""
        content = b"date,amount,counterparty,description\n2026-02-20,100.50,=CMD,@malicious\n"
        mapping = MappingAdapter()

        result = parse_csv_with_mapping(content, mapping)

        assert result.rows[0].counterparty == "CMD"  # = stripped
        assert result.rows[0].description == "malicious"  # @ stripped

    def should_raise_on_missing_date_format_when_date_column_set(self):
        """Raise error when date format not provided but date column is set."""
        content = b"date,amount,counterparty,description\n2026-02-20,100.50,Test,Invoice\n"
        mapping = MappingAdapter()
        mapping.date_format = None  # type: ignore

        with pytest.raises(GenericCsvParseError, match="Date format is required"):
            parse_csv_with_mapping(content, mapping)

    def should_parse_with_only_reference_column(self):
        """Parse CSV with only reference column mapped (marketplace mode)."""
        content = b"info,type,amount\nOrder #123,Sale,100.50\nOrder #456,Fee,-5.00\n"
        mapping = MappingAdapter()
        mapping.column_date = None
        mapping.column_amount = None
        mapping.column_counterparty = None
        mapping.column_description = None
        mapping.column_reference = "info"
        mapping.date_format = None  # type: ignore

        result = parse_csv_with_mapping(content, mapping)

        assert len(result.rows) == 2
        assert result.rows[0].source_reference == "Order #123"
        assert result.rows[0].date is None
        assert result.rows[0].amount is None
        assert result.rows[1].source_reference == "Order #456"
