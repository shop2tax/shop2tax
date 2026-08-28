"""SKR03 account model - curated subset for e-commerce bookkeeping."""

from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.accounting_pattern import AccountingPattern


class AccountCategory(str, Enum):
    """SKR03 account category."""

    REVENUE = "revenue"
    EXPENSE = "expense"
    NEUTRAL = "neutral"


class SKR03Account(Base):
    """Curated SKR03 account (~40 accounts for e-commerce)."""

    __tablename__ = "skr03_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Actual SKR03 number
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[AccountCategory] = mapped_column(SQLEnum(AccountCategory))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    bu_schluessel: Mapped[int | None] = mapped_column(Integer, nullable=True)  # DATEV BU-Key
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Relationships
    accounting_patterns: Mapped[list["AccountingPattern"]] = relationship(back_populates="skr03_account")
