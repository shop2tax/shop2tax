"""Receipt line item model for multi-position receipts."""

from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.receipt import Receipt
    from app.models.skr03 import SKR03Account


class TaxRule(str, Enum):
    """How tax is handled for a line item.

    Standard rules:
    - TAX_INCLUDED: Brutto (MwSt enthalten)
    - TAX_EXCLUDED: Netto (MwSt wird aufgeschlagen)
    - NO_TAX: Keine MwSt
    - REVERSE_CHARGE: Legacy generic RC (§13b UStG) — use specific variants below

    Reverse Charge variants (SevDesk-Pattern: 3 origins × 2 VSt states = 6):
    - Origin: EU (§13b Abs. 1) | DE (§13b Abs. 2) | NON_EU (§13b Abs. 2)
    - Input tax: WITH (Regelbesteuert → BU 94) | NO (Kleinunternehmer → BU 95)
    """

    # Standard rules
    TAX_INCLUDED = "tax_included"
    TAX_EXCLUDED = "tax_excluded"
    NO_TAX = "no_tax"
    REVERSE_CHARGE = "reverse_charge"  # Legacy — prefer specific variants

    # Reverse Charge: EU-Ausland (§13b Abs. 1) — Etsy, PayPal, Google, Meta
    REVERSE_CHARGE_EU_NO_INPUT_TAX = "rc_eu_no_vst"  # Kleinunternehmer → BU 95, Konto 3165
    REVERSE_CHARGE_EU_WITH_INPUT_TAX = "rc_eu_with_vst"  # Regelbesteuert → BU 94, Konto 3125

    # Reverse Charge: Deutschland (§13b Abs. 2) — Bauleistungen etc.
    REVERSE_CHARGE_DE_NO_INPUT_TAX = "rc_de_no_vst"
    REVERSE_CHARGE_DE_WITH_INPUT_TAX = "rc_de_with_vst"

    # Reverse Charge: Drittland (§13b Abs. 2) — Non-EU services (Canva etc.)
    REVERSE_CHARGE_NON_EU_NO_INPUT_TAX = "rc_non_eu_no_vst"
    REVERSE_CHARGE_NON_EU_WITH_INPUT_TAX = "rc_non_eu_with_vst"

    def is_reverse_charge(self) -> bool:
        """Check if this is any Reverse Charge variant."""
        return self.value.startswith("rc_") or self == TaxRule.REVERSE_CHARGE

    def has_input_tax(self) -> bool:
        """Check if input tax (Vorsteuer) is claimable. Only for Regelbesteuert RC variants."""
        return self.value.endswith("_with_vst")

    def bu_schluessel(self) -> int | None:
        """Get DATEV BU-Schlüssel for this tax rule.

        Returns:
            94 for RC with input tax (Regelbesteuert)
            95 for RC without input tax (Kleinunternehmer)
            None for non-RC rules (standard VAT handling via SKR03 account)
        """
        if not self.is_reverse_charge():
            return None
        if self.has_input_tax():
            return 94  # §13b MIT Vorsteuerabzug
        return 95  # §13b OHNE Vorsteuerabzug

    def suggested_skr03_account(self) -> int | None:
        """Get suggested SKR03 account for RC tax rules.

        Returns:
            3125 for RC with input tax (Leistungen §13b mit VSt)
            3165 for RC without input tax (Leistungen §13b ohne VSt)
            None for non-RC rules
        """
        if not self.is_reverse_charge():
            return None
        if self.has_input_tax():
            return 3125  # Leistungen §13b MIT VSt
        return 3165  # Leistungen §13b OHNE VSt


class ReceiptLineItem(Base):
    """Line item (position) on a receipt.

    Each receipt can have multiple positions, each with its own
    SKR03 account, amount, and tax rate.

    Example: An invoice with two items:
    - Position 1: 100€ to 6815 (Bürobedarf), 19% USt
    - Position 2:  50€ to 6830 (Gebühren), 19% USt
    """

    __tablename__ = "receipt_line_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    receipt_id: Mapped[str] = mapped_column(String(36), ForeignKey("receipts.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)  # Ordering (0-based)

    # Content
    description: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # Positive for regular items, negative for discounts

    # Accounting
    skr03_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("skr03_accounts.id"), nullable=True)
    tax_rule: Mapped[TaxRule] = mapped_column(SQLEnum(TaxRule), default=TaxRule.TAX_INCLUDED)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("19.00"))
    # RC tax rate persisted at creation time (GoBD: historical rate preserved)
    # Nullable for legacy items — they used implicit 0.19
    rc_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True, default=None)
    depreciation: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    receipt: Mapped["Receipt"] = relationship(back_populates="line_items")
    skr03_account: Mapped["SKR03Account | None"] = relationship()

    # --- Computed Properties ---

    @property
    def reverse_charge_tax_amount(self) -> Decimal | None:
        """Calculate Reverse Charge tax amount (§13b USt).

        For RC items, the stored `amount` is the net amount (Nettobetrag).
        This property calculates the USt that must be paid to Finanzamt.

        Uses persisted rc_tax_rate if available, otherwise DEFAULT_RC_TAX_RATE.

        Returns:
            USt amount for RC items, rounded to 2 decimal places.
            None for non-RC items.
        """
        if not self.tax_rule.is_reverse_charge():
            return None
        from app.core.constants import DEFAULT_RC_TAX_RATE

        rate = self.rc_tax_rate if self.rc_tax_rate is not None else DEFAULT_RC_TAX_RATE
        return (abs(self.amount) * rate).quantize(Decimal("0.01"))

    @property
    def effective_tax_rate(self) -> Decimal:
        """Get the effective tax rate for this line item.

        Returns:
            Persisted RC rate as percentage for RC items (e.g., 0.19 → 19.00)
            Otherwise: the stored tax_rate
        """
        if self.tax_rule.is_reverse_charge():
            from app.core.constants import DEFAULT_RC_TAX_RATE

            rate = self.rc_tax_rate if self.rc_tax_rate is not None else DEFAULT_RC_TAX_RATE
            return (rate * Decimal("100")).quantize(Decimal("0.01"))  # 0.19 → 19.00
        return self.tax_rate
