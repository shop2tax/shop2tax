"""SKR03 account Pydantic schemas."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.models.skr03 import AccountCategory

# Valid BU-Schlüssel values (DATEV tax keys)
# 2 = 7% USt (revenue), 3 = 19% USt (revenue)
# 8 = 7% VSt (expense), 9 = 19% VSt (expense)
BuSchluesselType = Literal[2, 3, 8, 9]

# Account class (first digit) to required category mapping
# 0xxx and 9xxx are not allowed
ACCOUNT_CLASS_TO_CATEGORY: dict[int, AccountCategory] = {
    1: AccountCategory.NEUTRAL,
    2: AccountCategory.NEUTRAL,
    3: AccountCategory.EXPENSE,
    4: AccountCategory.EXPENSE,
    5: AccountCategory.NEUTRAL,
    6: AccountCategory.NEUTRAL,
    7: AccountCategory.NEUTRAL,
    8: AccountCategory.REVENUE,
}


class SKR03AccountCreate(BaseModel):
    """Schema for creating a new SKR03 account."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    category: AccountCategory
    bu_schluessel: BuSchluesselType | None = None

    @field_validator("id")
    @classmethod
    def validate_account_id(cls, value: int) -> int:
        """Validate account ID is 4-digit and in allowed range (1000-8999)."""
        if value < 1000 or value > 8999:
            raise ValueError("Account ID must be between 1000 and 8999")
        account_class = value // 1000
        if account_class == 0 or account_class == 9:
            raise ValueError("Account classes 0xxx and 9xxx are not allowed")
        return value

    @model_validator(mode="after")
    def validate_category_matches_account_class(self) -> Self:
        """Validate category matches the account class (first digit)."""
        account_class = self.id // 1000
        expected_category = ACCOUNT_CLASS_TO_CATEGORY.get(account_class)
        if expected_category and self.category != expected_category:
            raise ValueError(f"Account {self.id} (class {account_class}xxx) requires category {expected_category.value}, got {self.category.value}")
        return self


class SKR03AccountUpdate(BaseModel):
    """Schema for updating an SKR03 account (partial update)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    active: bool | None = None
    bu_schluessel: BuSchluesselType | None = None


class SKR03AccountResponse(BaseModel):
    """Response schema for an SKR03 account."""

    id: int
    name: str
    category: AccountCategory
    active: bool
    bu_schluessel: int | None
    is_system: bool
