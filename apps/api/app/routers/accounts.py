"""SKR03 accounts router."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import raise_not_found
from app.database import get_db
from app.deps import CurrentUser, get_current_user
from app.models.skr03 import AccountCategory, SKR03Account
from app.schemas.skr03 import SKR03AccountCreate, SKR03AccountResponse, SKR03AccountUpdate
from app.services.response_builders import build_skr03_account_response

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


@router.get("", response_model=list[SKR03AccountResponse])
def list_accounts(
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
    category: AccountCategory | None = Query(None, description="Filter by category"),
    active_only: bool = Query(True, description="Only return active accounts"),
) -> list[SKR03AccountResponse]:
    """List all SKR03 accounts.

    Returns curated list of ~43 e-commerce relevant accounts.
    """
    query = select(SKR03Account)

    if category:
        query = query.where(SKR03Account.category == category)

    if active_only:
        query = query.where(SKR03Account.active.is_(True))

    # Order by account number (natural SKR03 ordering)
    query = query.order_by(SKR03Account.id)

    accounts = database.scalars(query).all()

    return [build_skr03_account_response(account) for account in accounts]


@router.get("/{account_id}", response_model=SKR03AccountResponse)
def get_account(
    account_id: int,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> SKR03AccountResponse:
    """Get a single SKR03 account by ID (account number)."""
    account = database.get(SKR03Account, account_id)

    if not account:
        raise_not_found("Account", str(account_id))

    return build_skr03_account_response(account)


@router.post("", response_model=SKR03AccountResponse, status_code=201)
def create_account(
    data: SKR03AccountCreate,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> SKR03AccountResponse:
    """Create a new SKR03 account.

    Validates:
    - Account ID must be 4-digit (1000-8999)
    - Account ID must be unique
    - Category must match account class (first digit)
    - BU-Schlüssel must be 2, 3, 8, or 9 (or None)
    """

    # Check for duplicate
    existing = database.get(SKR03Account, data.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Account {data.id} already exists")

    account = SKR03Account(
        id=data.id,
        name=data.name,
        category=data.category,
        bu_schluessel=data.bu_schluessel,
        active=True,
        is_system=False,
    )
    database.add(account)
    database.commit()
    database.refresh(account)

    return build_skr03_account_response(account)


@router.patch("/{account_id}", response_model=SKR03AccountResponse)
def update_account(
    account_id: int,
    data: SKR03AccountUpdate,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> SKR03AccountResponse:
    """Update an SKR03 account.

    Only name, active, and bu_schluessel can be changed.
    ID and category are immutable (would break DATEV export).
    """

    account = database.get(SKR03Account, account_id)
    if not account:
        raise_not_found("Account", str(account_id))

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(account, field, value)

    database.commit()
    database.refresh(account)

    return build_skr03_account_response(account)
