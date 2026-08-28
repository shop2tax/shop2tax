"""Pagination utilities for list endpoints.

Provides consistent limit/offset pagination with {items, total} response format.

IMPORTANT: All queries passed to paginate_query() MUST include ORDER BY with a
unique key (e.g., primary key as tiebreaker) to ensure deterministic results.
"""

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class PaginationParams:
    """Dependency for pagination parameters."""

    def __init__(
        self,
        limit: int = Query(100, ge=1, le=500, description="Maximum items to return"),
        offset: int = Query(0, ge=0, description="Number of items to skip"),
    ):
        self.limit = limit
        self.offset = offset


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated response format."""

    items: list[T]
    total: int


def paginate_query(
    session: Session,
    statement: Select,
    params: PaginationParams,
) -> tuple[list, int]:
    """Apply pagination to a SQLAlchemy 2.0 select statement.

    IMPORTANT: Statement MUST be ordered with a deterministic ORDER BY
    (include unique key as tiebreaker) before calling this function.

    Returns:
        Tuple of (items, total_count)
    """
    # Count total rows (without limit/offset)
    count_statement = select(func.count()).select_from(statement.subquery())
    total = session.execute(count_statement).scalar_one()

    # Apply pagination
    paginated = statement.offset(params.offset).limit(params.limit)
    items = list(session.scalars(paginated).unique().all())

    return items, total
