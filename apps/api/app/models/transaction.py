"""Transaction model."""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DATE, Boolean, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from app.models.source import TransactionSourceConfig
    from app.models.user import User


class Transaction(Base, TimestampMixin):
    """A single financial transaction entry."""

    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transaction_extra_data", "extra_data", postgresql_using="gin"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    date: Mapped[date] = mapped_column(DATE, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    counterparty: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    # Source configuration (Etsy, Amazon, DKB, etc.) - the sole source identifier
    source_config_id: Mapped[str] = mapped_column(String(36), ForeignKey("transaction_source_configs.id"), nullable=False, index=True)
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    import_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    oms_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_private: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # OMS partial payment tracking
    remaining_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Currency fields for non-EUR transactions (PayPal API sync)
    original_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)  # ISO 4217
    original_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    # Internal transfer (Geldbewegung) — bidirectional link
    linked_transfer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("transactions.id"), nullable=True)
    is_internal_transfer: Mapped[bool] = mapped_column(Boolean, default=False)

    # Structured marketplace data (D11: etsy_type, order_id, original_currency, etc.)
    # GIN-indexed for performant JSONB queries
    extra_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Timestamps (created_at/updated_at from TimestampMixin)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="transactions")
    source_config: Mapped["TransactionSourceConfig"] = relationship(back_populates="transactions")
    receipt_links: Mapped[list["ReceiptTransactionLink"]] = relationship(back_populates="transaction", cascade="all, delete-orphan")
    linked_transfer: Mapped["Transaction | None"] = relationship(
        remote_side="Transaction.id",
        foreign_keys=[linked_transfer_id],
        uselist=False,
    )
