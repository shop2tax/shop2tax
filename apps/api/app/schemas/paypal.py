"""PayPal sync Pydantic schemas."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, field_validator

from app.models.paypal_sync_log import PayPalSyncStatus

# --- Request Schemas ---


class PayPalSyncRequest(BaseModel):
    """Request to trigger a PayPal sync."""

    start_date: datetime.date
    end_date: datetime.date = datetime.date.today()

    @field_validator("end_date")
    @classmethod
    def validate_end_date_not_future(cls, end_date: datetime.date) -> datetime.date:
        if end_date > datetime.date.today():
            msg = "end_date cannot be in the future"
            raise ValueError(msg)
        return end_date


# --- Response Schemas ---


class PayPalSyncResponse(BaseModel):
    """Response from a PayPal sync operation."""

    imported_count: int
    skipped_count: int
    fee_count: int
    sync_log_id: str
    errors: list[str]


class PayPalSyncLogResponse(BaseModel):
    """Response for a single sync log entry."""

    id: str
    start_date: datetime.datetime
    end_date: datetime.datetime
    fetched_count: int
    imported_count: int
    fee_count: int
    status: PayPalSyncStatus
    error_message: str | None
    created_at: datetime.datetime


class PayPalSyncLogListResponse(BaseModel):
    """Paginated list of sync logs."""

    items: list[PayPalSyncLogResponse]
    total: int
