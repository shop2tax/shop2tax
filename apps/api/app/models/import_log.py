"""Import log model for tracking CSV imports."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.source import TransactionSourceConfig
    from app.models.user import User


class ImportLog(Base):
    """Tracks CSV import history.

    All imports are identified by source_config_id (FK to TransactionSourceConfig).
    """

    __tablename__ = "imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    source_config_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("transaction_source_configs.id"), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer)
    imported_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="imports")
    source_config: Mapped["TransactionSourceConfig"] = relationship()
