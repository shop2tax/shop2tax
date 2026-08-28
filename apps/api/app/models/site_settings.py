"""Site-wide settings (single-row table)."""

from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SiteSettings(Base):
    """Global site settings. Single row (id=1 always).

    NOT per-user — one instance = one company.
    Singleton enforced via CheckConstraint("id = 1").
    """

    __tablename__ = "site_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_site_settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_small_business: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tax_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vat_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # RC tax rate for Reverse Charge calculations (default 19% = 0.19)
    rc_tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default="0.1900")
    legal_form: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # DATEV export configuration (moved from User — tenant-wide, not per-user)
    # Schema: {"beraternummer": "1234567", "mandantennummer": "12345", "wirtschaftsjahr_beginn": "2025-01-01"}
    datev_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # 🤖 AI document extraction settings
    ai_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "gemini", "openai", "anthropic"
    ai_model: Mapped[str | None] = mapped_column(String(50), nullable=True)  # "gemini-2.5-flash", "gpt-4o-mini", etc.

    # OMS sync: set "shop2tax" label on synced orders
    oms_sync_set_labels: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
