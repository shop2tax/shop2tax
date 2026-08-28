"""rename billbee_store to oms_store

Revision ID: 6679a16559a9
Revises: c5217fa65264
Create Date: 2026-06-06 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6679a16559a9"
down_revision: Union[str, Sequence[str], None] = "c5217fa65264"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename Billbee store/sync-log tables to generic OMS, add provider_id FK."""
    # billbee_stores -> oms_stores
    op.rename_table("billbee_stores", "oms_stores")
    op.alter_column("oms_stores", "billbee_shop_id", new_column_name="external_shop_id")
    op.add_column("oms_stores", sa.Column("provider_id", sa.String(length=36), nullable=True))
    op.create_foreign_key("fk_oms_stores_provider_id", "oms_stores", "oms_providers", ["provider_id"], ["id"])
    op.create_index("ix_oms_stores_provider_id", "oms_stores", ["provider_id"])

    # Backfill provider_id with the seeded Billbee provider
    op.execute("UPDATE oms_stores SET provider_id = (SELECT id FROM oms_providers WHERE type = 'BILLBEE')")

    # billbee_sync_logs -> oms_sync_logs (+ enum type rename)
    op.execute("ALTER TYPE billbeesyncstatus RENAME TO omssyncstatus")
    op.rename_table("billbee_sync_logs", "oms_sync_logs")


def downgrade() -> None:
    """Revert OMS store/sync-log renames back to Billbee."""
    op.rename_table("oms_sync_logs", "billbee_sync_logs")
    op.execute("ALTER TYPE omssyncstatus RENAME TO billbeesyncstatus")

    op.drop_index("ix_oms_stores_provider_id", table_name="oms_stores")
    op.drop_constraint("fk_oms_stores_provider_id", "oms_stores", type_="foreignkey")
    op.drop_column("oms_stores", "provider_id")
    op.alter_column("oms_stores", "external_shop_id", new_column_name="billbee_shop_id")
    op.rename_table("oms_stores", "billbee_stores")
