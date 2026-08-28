"""OmsProviderRecord model for pluggable Order Management System providers."""

from enum import Enum
from uuid import uuid4

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin


class OmsProviderType(str, Enum):
    """Supported Order Management System provider types.

    The value carries the provider's brand identity (used in audit logs and
    API responses); the DB column stores the member name (SQLAlchemy default).
    """

    BILLBEE = "billbee"
    JTL = "jtl"
    XENTRAL = "xentral"


class OmsProviderRecord(Base, TimestampMixin):
    """Metadata for a configured OMS provider.

    Credentials stay in environment variables (see config.py); this table only
    stores type/display_name/is_active so the UI can render dynamic labels and
    conditionally show provider features.
    """

    __tablename__ = "oms_providers"
    __table_args__ = (UniqueConstraint("type", name="uq_oms_providers_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    type: Mapped[OmsProviderType] = mapped_column(SQLEnum(OmsProviderType))
    display_name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # created_at/updated_at from TimestampMixin
