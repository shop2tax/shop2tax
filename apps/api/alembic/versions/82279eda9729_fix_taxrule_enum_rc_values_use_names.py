"""fix_taxrule_enum_rc_values_use_names

PostgreSQL taxrule enum has mixed conventions:
- Old values use Python enum NAMES: TAX_INCLUDED, TAX_EXCLUDED, NO_TAX, REVERSE_CHARGE
- RC variants (added in 35a4ac8fd95f) use Python enum VALUES: rc_eu_no_vst, etc.

SQLAlchemy's SQLEnum sends enum .name by default, so RC inserts fail with:
  invalid input value for enum taxrule: "REVERSE_CHARGE_EU_NO_INPUT_TAX"

Fix: Rename RC enum values in DB to use names (matching SQLAlchemy's behavior).

Revision ID: 82279eda9729
Revises: fad56dbed22a
Create Date: 2026-03-02 11:03:33.567505

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "82279eda9729"
down_revision: Union[str, Sequence[str], None] = "fad56dbed22a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Map: old DB value (from migration 35a4ac8fd95f) → correct name (what SQLAlchemy sends)
RENAMES = {
    "rc_eu_no_vst": "REVERSE_CHARGE_EU_NO_INPUT_TAX",
    "rc_eu_with_vst": "REVERSE_CHARGE_EU_WITH_INPUT_TAX",
    "rc_de_no_vst": "REVERSE_CHARGE_DE_NO_INPUT_TAX",
    "rc_de_with_vst": "REVERSE_CHARGE_DE_WITH_INPUT_TAX",
    "rc_non_eu_no_vst": "REVERSE_CHARGE_NON_EU_NO_INPUT_TAX",
    "rc_non_eu_with_vst": "REVERSE_CHARGE_NON_EU_WITH_INPUT_TAX",
}


def upgrade() -> None:
    """Rename RC taxrule enum values from Python .value to Python .name."""
    for old_value, new_name in RENAMES.items():
        op.execute(f"ALTER TYPE taxrule RENAME VALUE '{old_value}' TO '{new_name}'")  # noqa: S608


def downgrade() -> None:
    """Rename RC taxrule enum values back to Python .value form."""
    for old_value, new_name in RENAMES.items():
        op.execute(f"ALTER TYPE taxrule RENAME VALUE '{new_name}' TO '{old_value}'")  # noqa: S608
