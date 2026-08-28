"""PayPal sync log model for tracking API sync history."""

from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class PayPalSyncStatus(str, Enum):
    """Status of a PayPal sync operation."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class PayPalSyncLog(Base):
    """Tracks PayPal API sync history."""

    __tablename__ = "paypal_sync_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    fee_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[PayPalSyncStatus] = mapped_column(SQLEnum(PayPalSyncStatus))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="paypal_sync_logs")
