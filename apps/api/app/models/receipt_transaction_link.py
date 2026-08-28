"""Junction table for receipt-to-transaction linking (M:N).

Enables:
- 1 Receipt → N Transactions (Sammelbeleg: Etsy-PDF → 200 Fee-Transaktionen)
- 1 Transaction → N Receipts (Sammelbuchung: Payout → Monatsrechnungen)
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.receipt import Receipt
    from app.models.transaction import Transaction


class ReceiptTransactionLink(Base):
    """Links a receipt to a transaction (M:N relationship).

    No unique constraints — both sides can have multiple links.
    Use cases:
    - Sammelbeleg: One Etsy-PDF receipt linked to 200+ fee transactions
    - Sammelbuchung: One transaction linked to multiple partial receipts
    """

    __tablename__ = "receipt_transaction_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    receipt_id: Mapped[str] = mapped_column(String(36), ForeignKey("receipts.id"), index=True)
    transaction_id: Mapped[str] = mapped_column(String(36), ForeignKey("transactions.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Relationships
    receipt: Mapped["Receipt"] = relationship(back_populates="transaction_links")
    transaction: Mapped["Transaction"] = relationship(back_populates="receipt_links")
