"""Drop UNIQUE constraint on receipt_id to enable M:N linking.

Enables 1 Receipt → N Transactions (Sammelbeleg pattern).
Use case: Etsy-PDF receipt linked to 200+ fee transactions.

Revision ID: fa461e0163f9
Revises: 35a4ac8fd95f
Create Date: 2026-03-01 11:18:33.305839
"""

from alembic import op

revision = "fa461e0163f9"
down_revision = "35a4ac8fd95f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop UNIQUE constraint to allow M:N linking."""
    op.drop_constraint("uq_receipt_transaction_link_receipt", "receipt_transaction_links", type_="unique")


def downgrade() -> None:
    """Restore UNIQUE constraint (only works if no duplicates exist)."""
    op.create_unique_constraint("uq_receipt_transaction_link_receipt", "receipt_transaction_links", ["receipt_id"])
