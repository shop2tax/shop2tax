"""Unit tests for the CSV delimiter validator (F4/F5).

A delimiter longer than one character makes pandas treat `sep` as a regular
expression (ReDoS / event-loop DoS), so GenericCsvMappingRequest only accepts a
single literal delimiter from the allowlist.
"""

import pytest
from app.schemas.csv import ALLOWED_CSV_DELIMITERS, GenericCsvMappingRequest
from pydantic import ValidationError


class TestCsvDelimiterValidation:
    """The delimiter field is constrained to a single allowlisted character."""

    def should_default_to_comma(self):
        assert GenericCsvMappingRequest().delimiter == ","

    def should_expose_the_expected_allowlist(self):
        assert ALLOWED_CSV_DELIMITERS == frozenset({",", ";", "\t", "|"})

    @pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
    def should_accept_allowlisted_single_characters(self, delimiter):
        assert GenericCsvMappingRequest(delimiter=delimiter).delimiter == delimiter

    @pytest.mark.parametrize(
        "delimiter",
        [
            "(a+)+$",  # catastrophic-backtracking regex
            "\\t",  # two-char string, NOT a real tab — must be rejected
            ",,",  # multi-char
            ";;",
            "",  # empty
            "a",  # single but not allowlisted
            "::",
        ],
    )
    def should_reject_multi_char_or_unlisted_delimiters(self, delimiter):
        with pytest.raises(ValidationError):
            GenericCsvMappingRequest(delimiter=delimiter)
