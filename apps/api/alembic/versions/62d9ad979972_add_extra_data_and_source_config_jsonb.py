"""add_extra_data_and_source_config_jsonb

Revision ID: 62d9ad979972
Revises: 80d57cbda001
Create Date: 2026-02-28 21:46:18.346354

Adds:
- extra_data JSONB column to transactions (for structured marketplace data)
- source_config JSONB column to transaction_source_configs (for marketplace-specific settings)
- GIN index on extra_data for performant JSONB queries
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "62d9ad979972"
down_revision: Union[str, Sequence[str], None] = "80d57cbda001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add extra_data JSONB to transactions (for marketplace-specific data like etsy_type, order_id)
    op.add_column("transactions", sa.Column("extra_data", JSONB, nullable=True))

    # Add GIN index for performant JSONB queries (e.g., WHERE extra_data->>'etsy_type' = 'FEE')
    op.create_index(
        "ix_transaction_extra_data",
        "transactions",
        ["extra_data"],
        unique=False,
        postgresql_using="gin",
    )

    # Add source_config JSONB to transaction_source_configs (for marketplace-specific settings)
    # Example: {"has_ust_id_registered": true, "etsy_vat_id": "IE9777587C"}
    op.add_column("transaction_source_configs", sa.Column("source_config", JSONB, nullable=True))

    # Migrate system source check_account_ids to virtual bank accounts (D4/D9)
    # Must use deferred approach: set to temp values first to avoid UNIQUE constraint conflicts
    # Old: Etsy=1200, Amazon=1201, Shopify=1202, Stripe=1203, PayPal=1204
    # New: Etsy=1201, Amazon=1202, Shopify=1203, Stripe=1204, PayPal=1210
    conn = op.get_bind()

    # Step 1: Move PayPal out of the way first (1204→1210, no conflict)
    conn.execute(sa.text("UPDATE transaction_source_configs SET check_account_id = 1210 WHERE id = 'a0000000-0000-0000-0000-000000000005'"))
    # Step 2: Now cascade in reverse order (Stripe, Shopify, Amazon, Etsy)
    conn.execute(sa.text("UPDATE transaction_source_configs SET check_account_id = 1204 WHERE id = 'a0000000-0000-0000-0000-000000000004'"))
    conn.execute(sa.text("UPDATE transaction_source_configs SET check_account_id = 1203 WHERE id = 'a0000000-0000-0000-0000-000000000003'"))
    conn.execute(sa.text("UPDATE transaction_source_configs SET check_account_id = 1202 WHERE id = 'a0000000-0000-0000-0000-000000000002'"))
    conn.execute(sa.text("UPDATE transaction_source_configs SET check_account_id = 1201 WHERE id = 'a0000000-0000-0000-0000-000000000001'"))

    # Step 3: Set source_config JSONB for all marketplace sources
    conn.execute(
        sa.text("""
        UPDATE transaction_source_configs
        SET source_config = '{"has_ust_id_registered": true, "vat_id": "IE9777587C"}'::jsonb
        WHERE id = 'a0000000-0000-0000-0000-000000000001'
    """)
    )
    conn.execute(
        sa.text("""
        UPDATE transaction_source_configs
        SET source_config = '{"has_ust_id_registered": true, "vat_id": "LU20260743"}'::jsonb
        WHERE id = 'a0000000-0000-0000-0000-000000000002'
    """)
    )
    conn.execute(
        sa.text("""
        UPDATE transaction_source_configs
        SET source_config = '{"has_ust_id_registered": true, "vat_id": "IE3347697KH"}'::jsonb
        WHERE id = 'a0000000-0000-0000-0000-000000000003'
    """)
    )
    conn.execute(
        sa.text("""
        UPDATE transaction_source_configs
        SET source_config = '{"has_ust_id_registered": true, "vat_id": "IE3396855EH"}'::jsonb
        WHERE id = 'a0000000-0000-0000-0000-000000000004'
    """)
    )
    conn.execute(
        sa.text("""
        UPDATE transaction_source_configs
        SET source_config = '{"has_ust_id_registered": true, "vat_id": "LU22046007"}'::jsonb
        WHERE id = 'a0000000-0000-0000-0000-000000000005'
    """)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("transaction_source_configs", "source_config")
    op.drop_index("ix_transaction_extra_data", table_name="transactions")
    op.drop_column("transactions", "extra_data")
