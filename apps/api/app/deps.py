"""FastAPI dependency injection."""

import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user import User

# System user for Local Mode (no OAuth configured)
SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"


@dataclass
class CurrentUser:
    """User extracted from X-User headers (set by Nuxt middleware)."""

    id: str
    name: str
    email: str


def get_current_user(
    x_user_id: str = Header("", alias="x-user-id"),
    x_user_name: str = Header("", alias="x-user-name"),
    x_user_email: str = Header("", alias="x-user-email"),
    x_proxy_secret: str = Header("", alias="x-proxy-secret"),
    database: Session = Depends(get_db),
) -> CurrentUser:
    """Extract user from X-User headers and ensure user exists in DB.

    Local Mode: Returns system user immediately, no proxy secret needed.
    Auth Mode: FAIL CLOSED — proxy secret required.

    Get-or-create: On first request, creates the User row so FK constraints
    on transactions, sync logs, etc. are satisfied.
    """
    settings = get_settings()

    # ⚠️ SECURITY: Local Mode Check FIRST, BEFORE proxy secret validation (Council N1)
    if settings.local_mode:
        return CurrentUser(id=SYSTEM_USER_ID, name="Local User", email="local@localhost")

    # Auth Mode: Validate proxy secret (fail closed)
    if not settings.allow_insecure_proxy_secret:
        if not settings.nuxt_proxy_secret:
            raise HTTPException(
                status_code=500,
                detail="Server misconfiguration: NUXT_PROXY_SECRET not set",
            )
        if not hmac.compare_digest(x_proxy_secret, settings.nuxt_proxy_secret):
            raise HTTPException(status_code=401, detail="Direct API access forbidden")

    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")

    # Ensure user exists in DB (get-or-create by provider_id)
    user = database.execute(select(User).where(User.provider_id == x_user_id)).scalar_one_or_none()

    if user is None:
        user = User(provider_id=x_user_id, provider_type="google", email=x_user_email, name=x_user_name)
        database.add(user)
        database.commit()
        database.refresh(user)

    return CurrentUser(
        id=user.id,
        name=user.name,
        email=user.email,
    )
