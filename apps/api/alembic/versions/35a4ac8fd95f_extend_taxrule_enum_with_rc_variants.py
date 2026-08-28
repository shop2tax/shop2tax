"""extend_taxrule_enum_with_rc_variants

Adds 6 new Reverse Charge variants to TaxRule enum (D12):
- rc_eu_no_vst / rc_eu_with_vst (EU-Ausland, §13b Abs. 1)
- rc_de_no_vst / rc_de_with_vst (Deutschland, §13b Abs. 2)
- rc_non_eu_no_vst / rc_non_eu_with_vst (Drittland, §13b Abs. 2)

Revision ID: 35a4ac8fd95f
Revises: 62d9ad979972
Create Date: 2026-03-01 08:51:04.838352

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "35a4ac8fd95f"
down_revision: Union[str, Sequence[str], None] = "62d9ad979972"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# New TaxRule enum values for Reverse Charge variants
NEW_TAXRULE_VALUES = [
    "rc_eu_no_vst",
    "rc_eu_with_vst",
    "rc_de_no_vst",
    "rc_de_with_vst",
    "rc_non_eu_no_vst",
    "rc_non_eu_with_vst",
]


def upgrade() -> None:
    """Add new Reverse Charge variants to TaxRule enum."""
    # PostgreSQL: ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
    # Must use op.execute() which handles this correctly.
    for value in NEW_TAXRULE_VALUES:
        # IF NOT EXISTS prevents errors when re-running migrations
        op.execute(f"ALTER TYPE taxrule ADD VALUE IF NOT EXISTS '{value}'")  # noqa: S608


def downgrade() -> None:
    """Downgrade: Cannot remove enum values in PostgreSQL without recreating the type.

    Since this is a non-production system and removing enum values is complex
    (requires recreating the type and updating all columns), we skip downgrade.
    """
    pass
