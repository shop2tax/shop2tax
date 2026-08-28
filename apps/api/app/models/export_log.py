"""Export log model for tracking DATEV exports."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DATE, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class ExportLog(Base):
    """Log entry for each DATEV export."""

    __tablename__ = "export_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    export_type: Mapped[str] = mapped_column(String(50), default="datev")  # For future export types
    export_format: Mapped[str] = mapped_column(String(10), default="csv")  # csv or zip
    transaction_count: Mapped[int] = mapped_column(Integer)
    line_item_count: Mapped[int] = mapped_column(Integer)
    date_from: Mapped[datetime | None] = mapped_column(DATE, nullable=True)
    date_to: Mapped[datetime | None] = mapped_column(DATE, nullable=True)
    beraternummer: Mapped[str] = mapped_column(String(20))
    mandantennummer: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="export_logs")
