"""add check constraint for payment_status

Revision ID: 29bc6f86ac1a
Revises: fa461e0163f9
Create Date: 2026-03-01 14:47:51.178517

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "29bc6f86ac1a"
down_revision: Union[str, Sequence[str], None] = "fa461e0163f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add CHECK constraint to ensure payment_status only accepts valid values."""
    op.create_check_constraint(
        "ck_receipt_payment_status",
        "receipts",
        "payment_status IN ('unpaid', 'partial', 'paid')",
    )


def downgrade() -> None:
    """Remove CHECK constraint for payment_status."""
    op.drop_constraint("ck_receipt_payment_status", "receipts", type_="check")
