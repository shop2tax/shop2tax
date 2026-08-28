"""Receipt model (Beleg) for revenue/expense tracking."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DATE, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin
from app.models.tag import receipt_tags

if TYPE_CHECKING:
    from app.models.receipt_audit_log import ReceiptAuditLog
    from app.models.receipt_line_item import ReceiptLineItem
    from app.models.receipt_transaction_link import ReceiptTransactionLink
    from app.models.tag import Tag
    from app.models.user import User


class ReceiptType(str, Enum):
    """Type of receipt (determines accounting direction)."""

    REVENUE = "revenue"  # Einnahme (from Billbee)
    EXPENSE = "expense"  # Ausgabe (manual entry)


class ReceiptStatus(str, Enum):
    """Lifecycle status of a receipt.

    State machine: draft → final → locked (via locked_at)
    - draft: Can be edited and deleted
    - final: Immutable (GoBD). Can only be soft-deleted if not linked.
    """

    DRAFT = "draft"
    FINAL = "final"


class Receipt(Base, TimestampMixin):
    """A receipt/invoice document (Beleg).

    Receipts represent accounting documents:
    - Revenue receipts: Invoices from Billbee (synced via pull)
    - Expense receipts: Manually created bills from suppliers

    GoBD compliance:
    - Content fields are immutable after finalization (status='final')
    - Files verified by SHA-256 hash
    - Soft delete only (never hard delete final receipts)
    - Audit log for all operations
    """

    __tablename__ = "receipts"
    __table_args__ = (
        # Partial unique index: prevents OMS order duplicates
        # WHERE clause allows soft-deleted rows to coexist with re-imports
        Index(
            "uq_receipt_oms_order",
            "oms_order_id",
            unique=True,
            postgresql_where="oms_order_id IS NOT NULL AND deleted_at IS NULL",
        ),
        CheckConstraint(
            "payment_status IN ('unpaid', 'partial', 'paid')",
            name="ck_receipt_payment_status",
        ),
    )

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))

    # Ownership (multi-tenant isolation)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)

    # Core receipt data (immutable after finalization)
    type: Mapped[ReceiptType] = mapped_column(SQLEnum(ReceiptType), index=True)
    receipt_number: Mapped[str] = mapped_column(String(100))  # Rechnungsnummer/Belegnummer
    date: Mapped[date_type] = mapped_column(DATE, index=True)  # Belegdatum
    counterparty: Mapped[str] = mapped_column(Text)  # Kunde (revenue) or Lieferant (expense)
    description: Mapped[str] = mapped_column(Text, default="")

    # New fields
    status: Mapped[ReceiptStatus] = mapped_column(SQLEnum(ReceiptStatus), default=ReceiptStatus.FINAL, index=True)
    due_date: Mapped[date_type | None] = mapped_column(DATE, nullable=True)  # Fälligkeit
    payment_date: Mapped[date_type | None] = mapped_column(DATE, nullable=True)  # Bezahldatum
    delivery_date: Mapped[date_type | None] = mapped_column(DATE, nullable=True)  # Lieferdatum
    delivery_period: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Lieferzeitraum
    currency: Mapped[str] = mapped_column(String(3), default="EUR")  # ISO 4217

    # Extraction audit trail: where did pre-filled data come from?
    extraction_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "zugferd", "gemini", "openai", "anthropic", "manual"

    # OMS provider fields (revenue receipts only)
    oms_provider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("oms_providers.id"), nullable=True, index=True)
    oms_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    oms_invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    oms_shop_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oms_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # File storage (optional, SHA-256 content-addressable)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256 hex
    file_storage_id: Mapped[str | None] = mapped_column(String(500), nullable=True)  # GCS object name
    file_original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Payment status (synced on link/unlink, not computed)
    payment_status: Mapped[str] = mapped_column(
        String(10),
        default="unpaid",
        index=True,
    )

    # GoBD locking (locked_at != None means locked, one-way: never unlock)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps (created_at/updated_at from TimestampMixin)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="receipts")
    audit_logs: Mapped[list["ReceiptAuditLog"]] = relationship(back_populates="receipt", cascade="all, delete-orphan")
    line_items: Mapped[list["ReceiptLineItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", order_by="ReceiptLineItem.position"
    )
    transaction_links: Mapped[list["ReceiptTransactionLink"]] = relationship(back_populates="receipt", cascade="all, delete-orphan")
    tags: Mapped[list["Tag"]] = relationship(secondary=receipt_tags, back_populates="receipts")

    @property
    def is_locked(self) -> bool:
        """Whether this receipt is locked (GoBD fiscal lock)."""
        return self.locked_at is not None

    @property
    def total_amount(self) -> Decimal:
        """Sum of all line item amounts."""
        return sum((item.amount for item in self.line_items), Decimal("0.00"))

    @property
    def total_reverse_charge_tax(self) -> Decimal:
        """Total Reverse Charge tax liability (§13b USt) across all line items.

        This is the "Steuerschuld §13b" that must be paid to Finanzamt.
        For Kleinunternehmer: This is an actual cost (not claimable).
        For Regelbesteuert: This neutralizes with input tax deduction.
        """
        total = Decimal("0.00")
        for item in self.line_items:
            rc_tax = item.reverse_charge_tax_amount
            if rc_tax is not None:
                total += rc_tax
        return total

    @property
    def has_reverse_charge_items(self) -> bool:
        """Check if this receipt has any Reverse Charge line items."""
        return any(item.tax_rule.is_reverse_charge() for item in self.line_items)
