"""Site settings router."""

import re
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings as get_app_settings
from app.database import get_db
from app.deps import CurrentUser, get_current_user
from app.models.site_settings import SiteSettings

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class PublicSettingsResponse(BaseModel):
    """Public settings visible on login page (unauthenticated)."""

    company_name: str | None = None


class SiteSettingsUpdate(BaseModel):
    """Update site settings."""

    model_config = ConfigDict(extra="forbid")

    company_name: str | None = None
    is_small_business: bool | None = None
    tax_number: str | None = None
    vat_id: str | None = None
    legal_form: str | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
    rc_tax_rate: Decimal | None = None  # 0.00–1.00 (e.g., 0.19 = 19%)
    oms_sync_set_labels: bool | None = None  # Set shop2tax label on synced orders

    @field_validator("vat_id")
    @classmethod
    def validate_vat_id(cls, value: str | None) -> str | None:
        if value is not None and value != "":
            if not re.match(r"^DE\d{9}$", value):
                msg = "VAT ID must follow the format DE + 9 digits (e.g. DE123456789)"
                raise ValueError(msg)
        return value or None

    @field_validator("rc_tax_rate")
    @classmethod
    def validate_rc_tax_rate(cls, value: Decimal | None) -> Decimal | None:
        if value is not None:
            if not (Decimal("0") <= value <= Decimal("1")):
                msg = "RC tax rate must be between 0 and 1 (e.g. 0.19 for 19%)"
                raise ValueError(msg)
        return value


class SiteSettingsResponse(BaseModel):
    """Full site settings response (authenticated)."""

    model_config = ConfigDict(from_attributes=True)

    company_name: str | None = None
    is_small_business: bool | None = None
    tax_number: str | None = None
    vat_id: str | None = None
    rc_tax_rate: Decimal  # Default 0.19
    legal_form: str | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
    oms_sync_set_labels: bool = True  # Set shop2tax label on synced orders


def _get_or_create_settings(database: Session) -> SiteSettings:
    """Get the single SiteSettings row, creating it if it doesn't exist."""
    settings = database.execute(select(SiteSettings).where(SiteSettings.id == 1)).scalar_one_or_none()
    if settings is None:
        settings = SiteSettings(id=1)
        database.add(settings)
        database.flush()
    return settings


# Provider → model list (must match MODEL_PRICING keys in document_extraction.py)
_PROVIDER_MODELS: dict[str, list[str]] = {
    "gemini": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"],
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1-nano"],
    "anthropic": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"],
}

# Provider → Settings attribute name
_PROVIDER_API_KEY_ATTRIBUTE: dict[str, str] = {
    "gemini": "gemini_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
}


class AIProviderResponse(BaseModel):
    """Single AI provider with available models."""

    provider: str
    models: list[str]


@router.get("/ai-providers", response_model=list[AIProviderResponse])
def get_available_ai_providers(
    user: CurrentUser = Depends(get_current_user),
) -> list[AIProviderResponse]:
    """Return available AI providers based on configured API keys.

    Only returns providers where the corresponding ENV key is set.
    """
    settings = get_app_settings()
    providers: list[AIProviderResponse] = []
    for provider, models in _PROVIDER_MODELS.items():
        attribute = _PROVIDER_API_KEY_ATTRIBUTE[provider]
        if getattr(settings, attribute, ""):
            providers.append(AIProviderResponse(provider=provider, models=models))
    return providers


@router.get("/public", response_model=PublicSettingsResponse)
def get_public_settings(
    database: Session = Depends(get_db),
) -> PublicSettingsResponse:
    """Get public settings (unauthenticated). Used by login page."""
    settings = _get_or_create_settings(database)
    database.commit()
    return PublicSettingsResponse(company_name=settings.company_name)


@router.get("", response_model=SiteSettingsResponse)
def get_settings(
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> SiteSettingsResponse:
    """Get full site settings (authenticated)."""
    settings = _get_or_create_settings(database)
    database.commit()
    return SiteSettingsResponse.model_validate(settings)


@router.patch("", response_model=SiteSettingsResponse)
def update_settings(
    body: SiteSettingsUpdate,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> SiteSettingsResponse:
    """Update site settings (authenticated)."""
    settings = _get_or_create_settings(database)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(settings, field, value)

    database.commit()
    database.refresh(settings)
    return SiteSettingsResponse.model_validate(settings)
