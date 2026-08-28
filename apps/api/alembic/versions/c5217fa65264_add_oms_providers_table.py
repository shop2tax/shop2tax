"""add oms_providers table

Revision ID: c5217fa65264
Revises: a72bcdd546cf
Create Date: 2026-06-06 09:00:00.000000

"""

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c5217fa65264"
down_revision: Union[str, Sequence[str], None] = "a72bcdd546cf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create oms_providers table and seed the Billbee provider record.

    The seed MUST live here (not only in lifespan) because the Phase 3 data
    migration references this record to backfill receipts.oms_provider_id.
    """
    oms_provider_type = postgresql.ENUM("BILLBEE", "JTL", "XENTRAL", name="omsprovidertype", create_type=False)
    oms_provider_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "oms_providers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("type", oms_provider_type, nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("type", name="uq_oms_providers_type"),
    )

    # Seed Billbee provider so the Phase 3 data migration can backfill receipts.
    op.execute(
        sa.text(
            "INSERT INTO oms_providers (id, type, display_name, is_active, created_at, updated_at) "
            "VALUES (:id, 'BILLBEE', 'Billbee', true, now(), now())"
        ).bindparams(id=str(uuid4()))
    )


def downgrade() -> None:
    """Drop oms_providers table and the omsprovidertype enum."""
    op.drop_table("oms_providers")
    postgresql.ENUM(name="omsprovidertype").drop(op.get_bind(), checkfirst=True)
