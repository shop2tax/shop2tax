"""OmsStore model for mapping store types to OMS provider shop IDs."""

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.oms_provider import OmsProviderRecord
    from app.models.source import TransactionSourceConfig
    from app.models.user import User


class OmsStore(Base, TimestampMixin):
    """Maps platform store types (Etsy, Amazon, etc.) to OMS provider shop IDs."""

    __tablename__ = "oms_stores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    provider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("oms_providers.id"), nullable=True, index=True)
    store_type: Mapped[str] = mapped_column(String(50))  # etsy, amazon, shopify, etc.
    label: Mapped[str] = mapped_column(String(255))  # User-friendly name
    external_shop_id: Mapped[int] = mapped_column(Integer)  # Provider's internal shop ID
    source_config_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("transaction_source_configs.id"), nullable=True)
    match_strategy: Mapped[str] = mapped_column(String(20), default="order_number")  # "order_number" or "email"
    # created_at/updated_at from TimestampMixin

    # Relationships
    user: Mapped["User"] = relationship(back_populates="oms_stores")
    provider: Mapped["OmsProviderRecord | None"] = relationship()
    source_config: Mapped["TransactionSourceConfig | None"] = relationship()
