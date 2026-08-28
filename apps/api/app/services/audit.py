"""Audit logging service for security events.

Logs security-relevant events with structured context.
Uses structlog for consistent JSON output in production.
"""

import structlog

# Configure structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO and above
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

audit_log = structlog.get_logger("audit")


def log_credential_change(user_id: str, credential_type: str, success: bool) -> None:
    """Log credential update events.

    Args:
        user_id: ID of the user whose credentials were changed
        credential_type: Type of credential (e.g., "billbee")
        success: Whether the operation succeeded
    """
    audit_log.info(
        "credential_change",
        user_id=user_id,
        credential_type=credential_type,
        success=success,
        event_type="security",
    )


def log_failed_auth(reason: str, user_id: str | None = None, ip_address: str | None = None) -> None:
    """Log authentication failures.

    Args:
        reason: Why authentication failed
        user_id: User ID if known (e.g., valid user but wrong credential)
        ip_address: Client IP address
    """
    audit_log.warning(
        "auth_failed",
        reason=reason,
        user_id=user_id,
        ip_address=ip_address,
        event_type="security",
    )


def log_datev_export(user_id: str, transaction_count: int, date_range: tuple[str, str] | None = None) -> None:
    """Log DATEV export events (sensitive financial data leaving system).

    Args:
        user_id: ID of the user performing export
        transaction_count: Number of transactions exported
        date_range: Optional tuple of (start_date, end_date)
    """
    audit_log.info(
        "datev_export",
        user_id=user_id,
        transaction_count=transaction_count,
        date_from=date_range[0] if date_range else None,
        date_to=date_range[1] if date_range else None,
        event_type="data_export",
    )


def log_bulk_import(user_id: str, source: str, row_count: int, success: bool) -> None:
    """Log bulk data import events.

    Args:
        user_id: ID of the user performing import
        source: Data source (e.g., "dkb", "paypal")
        row_count: Number of rows imported
        success: Whether import succeeded
    """
    audit_log.info(
        "bulk_import",
        user_id=user_id,
        source=source,
        row_count=row_count,
        success=success,
        event_type="data_import",
    )


def log_rate_limit_exceeded(ip_address: str, endpoint: str, limit: str) -> None:
    """Log rate limit exceeded events.

    Args:
        ip_address: Client IP that exceeded the limit
        endpoint: API endpoint path
        limit: The limit that was exceeded (e.g., "10/minute")
    """
    audit_log.warning(
        "rate_limit_exceeded",
        ip_address=ip_address,
        endpoint=endpoint,
        limit=limit,
        event_type="security",
    )
