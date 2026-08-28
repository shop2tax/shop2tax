"""User model for authentication (pluggable providers)."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.accounting_pattern import AccountingPattern
    from app.models.export_log import ExportLog
    from app.models.import_log import ImportLog
    from app.models.oms_store import OmsStore
    from app.models.oms_sync_log import OmsSyncLog
    from app.models.paypal_sync_log import PayPalSyncLog
    from app.models.receipt import Receipt
    from app.models.source import TransactionSourceConfig
    from app.models.transaction import Transaction


class User(Base):
    """User authenticated via pluggable auth provider (Google, GitHub, etc.) or Local Mode."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("provider_id", "provider_type", name="uq_user_provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider_id: Mapped[str] = mapped_column(String(255), index=True)
    provider_type: Mapped[str] = mapped_column(String(50), default="google")
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Relationships
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")
    imports: Mapped[list["ImportLog"]] = relationship(back_populates="user")
    export_logs: Mapped[list["ExportLog"]] = relationship(back_populates="user")
    accounting_patterns: Mapped[list["AccountingPattern"]] = relationship(back_populates="user")
    oms_stores: Mapped[list["OmsStore"]] = relationship(back_populates="user")
    receipts: Mapped[list["Receipt"]] = relationship(back_populates="user")
    paypal_sync_logs: Mapped[list["PayPalSyncLog"]] = relationship(back_populates="user")
    oms_sync_logs: Mapped[list["OmsSyncLog"]] = relationship(back_populates="user")
    source_configs: Mapped[list["TransactionSourceConfig"]] = relationship(back_populates="user")
