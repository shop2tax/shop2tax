"""Accounting pattern model for auto-suggestion learning."""

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.skr03 import SKR03Account
    from app.models.user import User


class AccountingPattern(Base):
    """Learned patterns for auto-suggesting SKR03 accounts."""

    __tablename__ = "accounting_patterns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    pattern: Mapped[str] = mapped_column(Text)
    skr03_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("skr03_accounts.id"))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    hits: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="accounting_patterns")
    skr03_account: Mapped["SKR03Account"] = relationship(back_populates="accounting_patterns")
