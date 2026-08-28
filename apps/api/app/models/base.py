"""Base mixins for SQLAlchemy models."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Mixin for created_at/updated_at timestamps.

    Uses both Python default (for existing DB rows via Alembic migrations)
    and server_default (for new tables via create_all, GoBD DDL documentation).

    GoBD: server_default ensures new tables have DB-level DEFAULT constraints.
    Alembic: Python default handles existing columns that predate this mixin.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
