"""PayPal sync router."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import PaginationParams, paginate_query
from app.database import get_db
from app.deps import CurrentUser, get_current_user
from app.models.paypal_sync_log import PayPalSyncLog
from app.schemas.paypal import (
    PayPalSyncLogListResponse,
    PayPalSyncLogResponse,
    PayPalSyncRequest,
    PayPalSyncResponse,
)
from app.services.paypal_client import PayPalApiError
from app.services.paypal_sync import sync
from app.services.response_builders import build_paypal_sync_log_response, build_paypal_sync_response

router = APIRouter(prefix="/api/v1/paypal", tags=["paypal"])


@router.post("/sync", response_model=PayPalSyncResponse)
def trigger_sync(
    data: PayPalSyncRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> PayPalSyncResponse:
    """Trigger a PayPal transaction sync for the given date range."""
    if data.start_date > data.end_date:
        raise HTTPException(status_code=422, detail="start_date must be before end_date")

    start_datetime = datetime.combine(data.start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_datetime = datetime.combine(data.end_date, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)

    try:
        result = sync(database, user.id, start_datetime, end_datetime)
    except PayPalApiError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return build_paypal_sync_response(result)


@router.get("/sync/history", response_model=PayPalSyncLogListResponse)
def list_sync_history(
    pagination: PaginationParams = Depends(),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> PayPalSyncLogListResponse:
    """List paginated sync history."""
    statement = select(PayPalSyncLog).order_by(PayPalSyncLog.created_at.desc(), PayPalSyncLog.id.desc())
    items, total = paginate_query(database, statement, pagination)

    return PayPalSyncLogListResponse(
        items=[build_paypal_sync_log_response(log) for log in items],
        total=total,
    )


@router.get("/sync/last", response_model=PayPalSyncLogResponse | None)
def get_last_sync(
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> PayPalSyncLogResponse | None:
    """Get the most recent sync log entry (for date pre-fill)."""
    statement = select(PayPalSyncLog).order_by(PayPalSyncLog.created_at.desc()).limit(1)
    log = database.execute(statement).scalar_one_or_none()
    if log is None:
        return None
    return build_paypal_sync_log_response(log)
