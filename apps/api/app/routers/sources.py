"""Transaction sources router."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import CHECK_ACCOUNT_MAX, CHECK_ACCOUNT_MIN
from app.core.exceptions import raise_not_found
from app.database import get_db
from app.deps import CurrentUser, get_current_user
from app.models.source import SourceType, TransactionSourceConfig
from app.models.transaction import Transaction
from app.schemas.source import (
    TransactionSourceConfigCreate,
    TransactionSourceConfigResponse,
    TransactionSourceConfigUpdate,
)
from app.services.response_builders import build_source_config_response

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


@router.get("", response_model=list[TransactionSourceConfigResponse])
def list_sources(
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
    type: SourceType | None = None,
) -> list[TransactionSourceConfigResponse]:
    """List all transaction sources.

    Returns all sources (marketplace mappings, API syncs, bank mappings).
    Optionally filter by type (marketplace_mapping/api_sync/csv_mapping).
    """
    statement = select(TransactionSourceConfig).order_by(TransactionSourceConfig.type, TransactionSourceConfig.check_account_id)

    if type is not None:
        statement = statement.where(TransactionSourceConfig.type == type)

    sources = database.scalars(statement).all()
    return [build_source_config_response(source) for source in sources]


def _check_duplicate_source_name(
    database: Session,
    name: str,
    exclude_id: str | None = None,
) -> None:
    """Raise 409 if a source with this name already exists."""
    conditions = [
        TransactionSourceConfig.name == name,
    ]
    if exclude_id is not None:
        conditions.append(TransactionSourceConfig.id != exclude_id)

    if database.scalars(select(TransactionSourceConfig).where(*conditions)).first():
        raise HTTPException(status_code=409, detail=f"Source with name '{name}' already exists")


def _get_next_check_account_id(database: Session) -> int:
    """Get the next available check_account_id in the 1200–1288 range.

    Finds the lowest unused number (fills gaps) instead of MAX+1.
    Raises 409 if all 89 slots are taken.
    """
    used_ids = set(database.scalars(select(TransactionSourceConfig.check_account_id)).all())
    for candidate in range(CHECK_ACCOUNT_MIN, CHECK_ACCOUNT_MAX + 1):
        if candidate not in used_ids:
            return candidate
    raise HTTPException(
        status_code=409,
        detail=f"Maximum number of payment accounts reached ({CHECK_ACCOUNT_MIN}–{CHECK_ACCOUNT_MAX})",
    )


def _check_check_account_id_available(
    database: Session,
    check_account_id: int,
    exclude_id: str | None = None,
) -> None:
    """Raise 409 if the check_account_id is already taken by another source."""
    conditions = [TransactionSourceConfig.check_account_id == check_account_id]
    if exclude_id is not None:
        conditions.append(TransactionSourceConfig.id != exclude_id)

    if database.scalars(select(TransactionSourceConfig).where(*conditions)).first():
        raise HTTPException(
            status_code=409,
            detail=f"Check account {check_account_id} is already assigned to another source",
        )


@router.post("", response_model=TransactionSourceConfigResponse, status_code=201)
def create_source(
    data: TransactionSourceConfigCreate,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> TransactionSourceConfigResponse:
    """Create a new source.

    User-created sources default to CSV_MAPPING type.
    check_account_id is auto-assigned if not provided.
    """
    _check_duplicate_source_name(database, data.name)

    # Auto-assign check_account_id if not provided, otherwise validate uniqueness
    if data.check_account_id is not None:
        _check_check_account_id_available(database, data.check_account_id)
        check_account_id = data.check_account_id
    else:
        check_account_id = _get_next_check_account_id(database)

    source = TransactionSourceConfig(
        user_id=user.id,
        name=data.name,
        type=data.type,
        check_account_id=check_account_id,
    )
    # Apply source_config if provided (same merge pattern as update)
    if data.source_config:
        config_data = data.source_config.model_dump(exclude_unset=True)
        source.source_config = {k: v for k, v in config_data.items() if v is not None}

    database.add(source)
    database.commit()
    database.refresh(source)

    return build_source_config_response(source)


@router.get("/{source_id}", response_model=TransactionSourceConfigResponse)
def get_source(
    source_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> TransactionSourceConfigResponse:
    """Get a single source by ID."""
    source = database.get(TransactionSourceConfig, source_id)

    if not source:
        raise_not_found("Source", source_id)

    return build_source_config_response(source)


@router.put("/{source_id}", response_model=TransactionSourceConfigResponse)
def update_source(
    source_id: str,
    data: TransactionSourceConfigUpdate,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> TransactionSourceConfigResponse:
    """Update a source.

    All sources can be updated except system CSV_PARSER and API_SYNC sources.
    """
    source = database.get(TransactionSourceConfig, source_id)

    if not source:
        raise_not_found("Source", source_id)

    # Block editing system sources (built-in marketplace, API sync)
    if source.user_id is None and source.type in (SourceType.CSV_PARSER, SourceType.API_SYNC, SourceType.MARKETPLACE_MAPPING):
        raise HTTPException(status_code=403, detail="Cannot update system sources")

    # Check for duplicate name if name is being changed
    update_data = data.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] != source.name:
        _check_duplicate_source_name(database, update_data["name"], exclude_id=source_id)

    # Check for check_account_id uniqueness if being changed
    if "check_account_id" in update_data and update_data["check_account_id"] != source.check_account_id:
        _check_check_account_id_available(database, update_data["check_account_id"], exclude_id=source_id)

    # Handle source_config merge (partial update, not full replace)
    if "source_config" in update_data and update_data["source_config"] is not None:
        # Merge new config with existing
        existing_config = source.source_config or {}
        new_config_data = update_data["source_config"]
        if isinstance(new_config_data, dict):
            for key, value in new_config_data.items():
                if value is not None:
                    existing_config[key] = value
        source.source_config = existing_config
        del update_data["source_config"]

    for key, value in update_data.items():
        setattr(source, key, value)

    database.commit()
    database.refresh(source)

    return build_source_config_response(source)


@router.delete("/{source_id}", status_code=204)
def delete_source(
    source_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> None:
    """Delete a source.

    All sources can be deleted except system CSV_PARSER and API_SYNC sources,
    and sources with linked transactions.
    """
    source = database.get(TransactionSourceConfig, source_id)

    if not source:
        raise_not_found("Source", source_id)

    # Block deleting system sources (built-in marketplace, API sync)
    if source.user_id is None and source.type in (SourceType.CSV_PARSER, SourceType.API_SYNC, SourceType.MARKETPLACE_MAPPING):
        raise HTTPException(status_code=403, detail="Cannot delete system sources")

    # Check if source has transactions
    if source.transactions:
        raise HTTPException(status_code=409, detail="Cannot delete source with linked transactions")

    # Also delete mapping profile if exists
    if source.mapping_profile:
        database.delete(source.mapping_profile)

    database.delete(source)
    database.commit()


class ClearingAccountBalance(BaseModel):
    """Balance of a source's clearing account (check_account_id)."""

    source_id: str
    source_name: str
    check_account_id: int
    balance: Decimal  # Sum of all non-deleted transactions for this source
    transaction_count: int
    is_negative: bool  # Warning: missing transactions?


@router.get("/{source_id}/balance", response_model=ClearingAccountBalance)
def get_source_balance(
    source_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> ClearingAccountBalance:
    """Get the clearing account balance for a source.

    Sums all non-deleted transactions for this source.
    Positive balance = funds still in clearing account (e.g., unpaid payouts).
    Negative balance = possible missing transactions (warning).
    """
    source = database.get(TransactionSourceConfig, source_id)

    if not source:
        raise_not_found("Source", source_id)

    result = database.execute(
        select(
            func.coalesce(func.sum(Transaction.amount), 0).label("balance"),
            func.count().label("transaction_count"),
        ).where(
            Transaction.source_config_id == source_id,
            Transaction.deleted_at.is_(None),
        )
    ).one()

    balance = Decimal(str(result.balance))

    return ClearingAccountBalance(
        source_id=source.id,
        source_name=source.name,
        check_account_id=source.check_account_id,
        balance=balance,
        transaction_count=result.transaction_count,
        is_negative=balance < 0,
    )
