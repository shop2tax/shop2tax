"""CSV mapping profiles router."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import raise_not_found
from app.database import get_db
from app.deps import CurrentUser, get_current_user
from app.models.source import CsvMappingProfile, TransactionSourceConfig
from app.schemas.source import (
    CsvMappingProfileCreate,
    CsvMappingProfileResponse,
    CsvMappingProfileUpdate,
)
from app.services.response_builders import build_mapping_profile_response

router = APIRouter(prefix="/api/v1/mappings", tags=["mappings"])


@router.get("", response_model=list[CsvMappingProfileResponse])
def list_mappings(
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> list[CsvMappingProfileResponse]:
    """List all CSV mapping profiles."""
    statement = select(CsvMappingProfile).order_by(CsvMappingProfile.created_at.desc(), CsvMappingProfile.id.desc())

    mappings = database.scalars(statement).all()
    return [build_mapping_profile_response(mapping) for mapping in mappings]


@router.get("/by-source/{source_id}", response_model=CsvMappingProfileResponse | None)
def get_mapping_by_source(
    source_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> CsvMappingProfileResponse | None:
    """Get mapping profile for a specific source.

    Returns the mapping for the given source, or null if none exists.
    Returns 404 only if the source itself doesn't exist.
    """
    # Verify source exists
    source = database.get(TransactionSourceConfig, source_id)
    if not source:
        raise_not_found("Source", source_id)

    # Find mapping for this source
    mapping = database.scalars(
        select(CsvMappingProfile).where(
            CsvMappingProfile.source_id == source_id,
        )
    ).first()

    if not mapping:
        return None

    return build_mapping_profile_response(mapping)


@router.post("", response_model=CsvMappingProfileResponse, status_code=201)
def create_or_update_mapping(
    data: CsvMappingProfileCreate,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> CsvMappingProfileResponse:
    """Create or update a CSV mapping profile.

    Upserts by source_id — one mapping per source (shared tenant).
    """
    # Verify source exists
    source = database.get(TransactionSourceConfig, data.source_id)
    if not source:
        raise_not_found("Source", data.source_id)

    # Check for existing mapping for this source
    existing = database.scalars(
        select(CsvMappingProfile).where(
            CsvMappingProfile.source_id == data.source_id,
        )
    ).first()

    if existing:
        # Update existing mapping
        update_data = data.model_dump(exclude={"source_id"})
        for key, value in update_data.items():
            setattr(existing, key, value)
        database.commit()
        database.refresh(existing)
        return build_mapping_profile_response(existing)

    # Create new mapping
    mapping = CsvMappingProfile(
        user_id=user.id,
        source_id=data.source_id,
        name=data.name,
        delimiter=data.delimiter,
        encoding=data.encoding,
        has_header=data.has_header,
        skip_rows=data.skip_rows,
        date_format=data.date_format,
        amount_format=data.amount_format,
        column_date=data.column_date,
        column_amount=data.column_amount,
        column_counterparty=data.column_counterparty,
        column_description=data.column_description,
        column_reference=data.column_reference,
    )
    database.add(mapping)
    database.commit()
    database.refresh(mapping)

    return build_mapping_profile_response(mapping)


@router.put("/{mapping_id}", response_model=CsvMappingProfileResponse)
def update_mapping(
    mapping_id: str,
    data: CsvMappingProfileUpdate,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> CsvMappingProfileResponse:
    """Update a CSV mapping profile."""
    mapping = database.get(CsvMappingProfile, mapping_id)

    if not mapping:
        raise_not_found("Mapping", mapping_id)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(mapping, key, value)

    database.commit()
    database.refresh(mapping)

    return build_mapping_profile_response(mapping)


@router.delete("/{mapping_id}", status_code=204)
def delete_mapping(
    mapping_id: str,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> None:
    """Delete a CSV mapping profile."""
    mapping = database.get(CsvMappingProfile, mapping_id)

    if not mapping:
        raise_not_found("Mapping", mapping_id)

    database.delete(mapping)
    database.commit()
