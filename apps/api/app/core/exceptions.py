"""Common HTTP exception helpers."""

from typing import Never

from fastapi import HTTPException


def raise_not_found(resource: str, identifier: str | None = None) -> Never:
    """Raise 404 HTTPException with consistent message format.

    Args:
        resource: Name of the resource (e.g., "Transaction", "Receipt")
        identifier: Optional identifier to include in message

    Raises:
        HTTPException: Always raises with status_code=404
    """
    detail = f"{resource} not found"
    if identifier:
        detail = f"{resource} '{identifier}' not found"
    raise HTTPException(status_code=404, detail=detail)
