"""Transaction source configuration and CSV mapping profile models."""

from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.user import User


class SourceType(str, Enum):
    """Type of transaction source.

    CSV_PARSER: Legacy built-in marketplace parser. Read-only — existing records must not be deleted,
        but no new sources of this type are created. Web UI filters it out of the create/edit form.
        Migration path: replace with MARKETPLACE_MAPPING (user-configurable column mapping).
    API_SYNC: API integration (PayPal)
    CSV_MAPPING: User-configured CSV column mapping (DKB, Finom, custom banks)
    MARKETPLACE_MAPPING: User-configured CSV mapping for marketplaces (Etsy, Amazon, Shopify, Stripe)
    """

    CSV_PARSER = "csv_parser"  # Legacy — read-only, no new records, web UI hides from create form
    API_SYNC = "api_sync"
    CSV_MAPPING = "csv_mapping"
    MARKETPLACE_MAPPING = "marketplace_mapping"


class TransactionSourceConfig(Base, TimestampMixin):
    """A transaction source (bank or marketplace).

    System sources (marketplaces) have user_id=NULL.
    User-created bank sources have user_id set.

    check_account_id: SKR03 Buchungskonto (1200-1288) for DATEV Gegenkonto.
    Auto-assigned on creation, can be manually overridden.
    """

    __tablename__ = "transaction_source_configs"
    __table_args__ = (UniqueConstraint("check_account_id", name="uq_source_check_account_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[SourceType] = mapped_column(SQLEnum(SourceType))
    check_account_id: Mapped[int] = mapped_column(Integer)

    # Marketplace-specific configuration (D3: has_ust_id_registered, etsy_vat_id, etc.)
    # Example: {"has_ust_id_registered": true, "vat_id": "IE9777587C"}
    source_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # created_at/updated_at from TimestampMixin

    # Relationships
    user: Mapped["User | None"] = relationship(back_populates="source_configs")
    mapping_profile: Mapped["CsvMappingProfile | None"] = relationship(back_populates="source_config", uselist=False)
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="source_config")


class CsvMappingProfile(Base, TimestampMixin):
    """Saved CSV column mapping for a specific source.

    One mapping per source per user (enforced by unique constraint).
    Stores CSV parsing options and column-to-field assignments.
    """

    __tablename__ = "csv_mapping_profiles"
    __table_args__ = (UniqueConstraint("source_id", name="uq_mapping_source"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("transaction_source_configs.id"))
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # CSV parsing options
    delimiter: Mapped[str] = mapped_column(String(5), default=",")
    encoding: Mapped[str] = mapped_column(String(20), default="utf-8")
    has_header: Mapped[bool] = mapped_column(Boolean, default=True)
    skip_rows: Mapped[int] = mapped_column(Integer, default=0)
    date_format: Mapped[str | None] = mapped_column(String(30), nullable=True)
    amount_format: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "german" or "english"

    # Column assignments (all nullable — marketplace only needs reference)
    column_date: Mapped[str | None] = mapped_column(String(100), nullable=True)
    column_amount: Mapped[str | None] = mapped_column(String(100), nullable=True)
    column_counterparty: Mapped[str | None] = mapped_column(String(100), nullable=True)
    column_description: Mapped[str | None] = mapped_column(String(100), nullable=True)
    column_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Filter column (for marketplace imports — filter out Fee/Deposit rows)
    column_filter: Mapped[str | None] = mapped_column(String(100), nullable=True)
    filter_include_values: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # created_at/updated_at from TimestampMixin

    # Relationships
    user: Mapped["User"] = relationship()
    source_config: Mapped["TransactionSourceConfig"] = relationship(back_populates="mapping_profile")
