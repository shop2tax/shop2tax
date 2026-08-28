"""Tag model for receipt categorization."""

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.receipt import Receipt
    from app.models.user import User

# M:N junction table for receipt tags
receipt_tags = Table(
    "receipt_tags",
    Base.metadata,
    Column("receipt_id", String(36), ForeignKey("receipts.id"), primary_key=True),
    Column("tag_id", String(36), ForeignKey("tags.id"), primary_key=True),
)


class Tag(Base):
    """User-defined tag for categorizing receipts."""

    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)

    # Relationships
    user: Mapped["User"] = relationship()
    receipts: Mapped[list["Receipt"]] = relationship(secondary=receipt_tags, back_populates="tags")
