"""SQL utility functions."""


def escape_like(value: str) -> str:
    """Escape SQL LIKE/ILIKE wildcard characters in a user-provided string.

    Prevents '%' and '_' in user input from being interpreted as wildcards.
    Uses backslash as the escape character (PostgreSQL default).
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
