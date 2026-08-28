"""Tags router for receipt categorization."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser, get_current_user
from app.models.tag import Tag
from app.schemas.receipt import TagResponse

router = APIRouter(prefix="/api/v1/tags", tags=["tags"])


@router.get("", response_model=list[TagResponse])
def list_tags(
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> list[TagResponse]:
    """List all tags (shared tenant, for autocomplete)."""
    tags = database.scalars(select(Tag).order_by(Tag.name)).all()

    return [TagResponse(id=tag.id, name=tag.name) for tag in tags]
