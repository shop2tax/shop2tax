"""rename billbee fields to oms

Revision ID: e77bb53aec45
Revises: 6679a16559a9
Create Date: 2026-06-06 11:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e77bb53aec45"
down_revision: Union[str, Sequence[str], None] = "6679a16559a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename receipt/transaction/site_settings billbee_* columns to oms_*."""
    # receipts: drop old partial unique index, rename columns, add provider FK
    op.drop_index("uq_receipt_billbee_order", table_name="receipts")
    op.alter_column("receipts", "billbee_order_id", new_column_name="oms_order_id")
    op.alter_column("receipts", "billbee_invoice_number", new_column_name="oms_invoice_number")
    op.alter_column("receipts", "billbee_shop_name", new_column_name="oms_shop_name")
    op.alter_column("receipts", "billbee_platform", new_column_name="oms_platform")
    op.execute("ALTER INDEX ix_receipts_billbee_order_id RENAME TO ix_receipts_oms_order_id")

    op.add_column("receipts", sa.Column("oms_provider_id", sa.String(length=36), nullable=True))
    op.create_foreign_key("fk_receipts_oms_provider_id", "receipts", "oms_providers", ["oms_provider_id"], ["id"])
    op.create_index("ix_receipts_oms_provider_id", "receipts", ["oms_provider_id"])
    op.create_index(
        "uq_receipt_oms_order",
        "receipts",
        ["oms_order_id"],
        unique=True,
        postgresql_where=sa.text("oms_order_id IS NOT NULL AND deleted_at IS NULL"),
    )

    # Backfill provider for receipts that came from the (Billbee) OMS
    op.execute("UPDATE receipts SET oms_provider_id = (SELECT id FROM oms_providers WHERE type = 'BILLBEE') WHERE oms_order_id IS NOT NULL")

    # transactions
    op.alter_column("transactions", "billbee_order_id", new_column_name="oms_order_id")
    op.execute("ALTER INDEX ix_transactions_billbee_order_id RENAME TO ix_transactions_oms_order_id")

    # site_settings
    op.alter_column("site_settings", "billbee_sync_set_labels", new_column_name="oms_sync_set_labels")

    # Clean up index/constraint names left behind by the Phase 2 table renames
    op.execute("ALTER INDEX billbee_stores_pkey RENAME TO oms_stores_pkey")
    op.execute("ALTER INDEX ix_billbee_stores_user_id RENAME TO ix_oms_stores_user_id")
    op.execute("ALTER INDEX billbee_sync_logs_pkey RENAME TO oms_sync_logs_pkey")
    op.execute("ALTER INDEX ix_billbee_sync_logs_user_id RENAME TO ix_oms_sync_logs_user_id")


def downgrade() -> None:
    """Revert oms_* columns back to billbee_*."""
    op.execute("ALTER INDEX ix_oms_sync_logs_user_id RENAME TO ix_billbee_sync_logs_user_id")
    op.execute("ALTER INDEX oms_sync_logs_pkey RENAME TO billbee_sync_logs_pkey")
    op.execute("ALTER INDEX ix_oms_stores_user_id RENAME TO ix_billbee_stores_user_id")
    op.execute("ALTER INDEX oms_stores_pkey RENAME TO billbee_stores_pkey")

    op.alter_column("site_settings", "oms_sync_set_labels", new_column_name="billbee_sync_set_labels")

    op.execute("ALTER INDEX ix_transactions_oms_order_id RENAME TO ix_transactions_billbee_order_id")
    op.alter_column("transactions", "oms_order_id", new_column_name="billbee_order_id")

    op.drop_index("uq_receipt_oms_order", table_name="receipts")
    op.drop_index("ix_receipts_oms_provider_id", table_name="receipts")
    op.drop_constraint("fk_receipts_oms_provider_id", "receipts", type_="foreignkey")
    op.drop_column("receipts", "oms_provider_id")
    op.execute("ALTER INDEX ix_receipts_oms_order_id RENAME TO ix_receipts_billbee_order_id")
    op.alter_column("receipts", "oms_platform", new_column_name="billbee_platform")
    op.alter_column("receipts", "oms_shop_name", new_column_name="billbee_shop_name")
    op.alter_column("receipts", "oms_invoice_number", new_column_name="billbee_invoice_number")
    op.alter_column("receipts", "oms_order_id", new_column_name="billbee_order_id")
    op.create_index(
        "uq_receipt_billbee_order",
        "receipts",
        ["billbee_order_id"],
        unique=True,
        postgresql_where=sa.text("billbee_order_id IS NOT NULL AND deleted_at IS NULL"),
    )
