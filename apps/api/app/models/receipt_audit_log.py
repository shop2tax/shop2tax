"""Receipt audit log for GoBD compliance tracking."""

from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.receipt import Receipt
    from app.models.user import User


class ReceiptAuditAction(str, Enum):
    """Actions tracked in the receipt audit log."""

    CREATED = "created"  # Receipt created (from Billbee sync or manual)
    UPDATED = "updated"  # Draft receipt updated
    FINALIZED = "finalized"  # Draft → Final transition
    LINKED = "linked"  # Linked to a payment (Transaction)
    UNLINKED = "unlinked"  # Unlinked from a payment
    DELETED = "deleted"  # Soft-deleted
    REVERTED = "reverted"  # Final → Draft revert (before lock)
    LOCKED = "locked"  # Locked for fiscal year finalization
    PAYMENT_RECORDED = "payment_recorded"  # Manual payment created and linked
    FILE_UPLOADED = "file_uploaded"  # File stored in GCS
    FILE_DOWNLOADED = "file_downloaded"  # File retrieved from GCS


class ReceiptAuditLog(Base):
    """Audit log entry for receipt operations.

    GoBD requires tracking all operations on accounting documents.
    This log provides the audit trail (Nachvollziehbarkeit).
    """

    __tablename__ = "receipt_audit_logs"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))

    # Foreign keys
    receipt_id: Mapped[str] = mapped_column(String(36), ForeignKey("receipts.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)

    # Audit data
    action: Mapped[ReceiptAuditAction] = mapped_column(SQLEnum(ReceiptAuditAction), index=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # e.g., {"transaction_id": "..."}

    # Timestamp (immutable, no updated_at)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Relationships
    receipt: Mapped["Receipt"] = relationship(back_populates="audit_logs")
    user: Mapped["User"] = relationship()
