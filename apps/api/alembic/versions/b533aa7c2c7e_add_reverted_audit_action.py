"""add_reverted_audit_action

Revision ID: b533aa7c2c7e
Revises: 82279eda9729
Create Date: 2026-03-02 12:29:45.954176

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b533aa7c2c7e"
down_revision: Union[str, Sequence[str], None] = "82279eda9729"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'REVERTED' value to receiptauditaction enum."""
    op.execute("ALTER TYPE receiptauditaction ADD VALUE IF NOT EXISTS 'REVERTED'")


def downgrade() -> None:
    """PostgreSQL does not support removing enum values."""
