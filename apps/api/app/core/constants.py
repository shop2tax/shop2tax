"""Shared constants used across routers, schemas, and services."""

from decimal import Decimal

# Default RC tax rate — used as fallback when SiteSettings not available or LineItem has no persisted rate
DEFAULT_RC_TAX_RATE = Decimal("0.19")

# SKR03 check account range for payment accounts (Bank/Kasse)
# 1200–1288: Bank accounts, 1590: Durchlaufende Posten (transit items)
CHECK_ACCOUNT_MIN = 1200
CHECK_ACCOUNT_MAX = 1288
CHECK_ACCOUNT_SPECIAL = 1590  # Durchlaufende Posten


def is_valid_check_account(value: int) -> bool:
    """Validate SKR03 check account: 1200-1288 or 1590."""
    return (CHECK_ACCOUNT_MIN <= value <= CHECK_ACCOUNT_MAX) or value == CHECK_ACCOUNT_SPECIAL


# German month names for period labels (index 0 = Januar)
GERMAN_MONTHS = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]

# German → English month mapping for date parsing (lowercase keys)
GERMAN_TO_ENGLISH_MONTHS = {
    "januar": "January",
    "februar": "February",
    "märz": "March",
    "april": "April",
    "mai": "May",
    "juni": "June",
    "juli": "July",
    "august": "August",
    "september": "September",
    "oktober": "October",
    "november": "November",
    "dezember": "December",
}
