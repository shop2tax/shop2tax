"""Export router for DATEV and other export formats."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import PaginationParams, paginate_query
from app.database import get_db
from app.deps import CurrentUser, get_current_user
from app.models.export_log import ExportLog
from app.schemas.datev import (
    DatevConfig,
    DatevExportRequest,
    DatevExportResponse,
    DatevValidationResult,
    DatevZipExportRequest,
    ExportHistoryResponse,
)
from app.services.datev import DatevExportService

router = APIRouter(prefix="/api/v1/export", tags=["export"])


# --- DATEV Settings Endpoints ---


@router.get("/datev/settings", response_model=DatevConfig | None)
def get_datev_settings(
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> DatevConfig | None:
    """Get stored DATEV configuration (tenant-wide).

    Returns None if no config is stored.
    """
    from app.models.site_settings import SiteSettings

    site_settings = database.get(SiteSettings, 1)
    if not site_settings or not site_settings.datev_config:
        return None
    return DatevConfig(**site_settings.datev_config)


@router.put("/datev/settings", response_model=DatevConfig)
def update_datev_settings(
    config: DatevConfig,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> DatevConfig:
    """Store DATEV configuration (tenant-wide).

    Saves Beraternummer, Mandantennummer, and Wirtschaftsjahr-Beginn
    so they don't need to be entered on every export.
    """
    from app.models.site_settings import SiteSettings

    site_settings = database.get(SiteSettings, 1)
    if not site_settings:
        site_settings = SiteSettings(id=1)
        database.add(site_settings)
    site_settings.datev_config = config.model_dump(mode="json")
    database.commit()
    return config


def _run_export(
    database: Session,
    request: DatevExportRequest,
) -> DatevExportResponse:
    """Run DATEV export with standard argument unpacking."""
    service = DatevExportService(database)
    return service.export(
        config=request.config,
        date_from=request.date_from,
        date_to=request.date_to,
        include_unreconciled=request.include_unreconciled,
    )


@router.post("/datev", response_model=DatevExportResponse)
def export_datev(
    request: DatevExportRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> DatevExportResponse:
    """Generate DATEV Buchungsstapel export.

    Returns JSON with header block, column headers, data rows, and complete CSV content.
    Use the `csv_content` field to download the file.
    """
    return _run_export(database, request)


@router.post("/datev/download")
def export_datev_download(
    request: DatevExportRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> PlainTextResponse:
    """Generate and download DATEV Buchungsstapel CSV file.

    Returns the CSV file directly for download and logs the export.
    """
    export = _run_export(database, request)

    # Generate filename with date range
    date_from_str = request.date_from.strftime("%Y%m%d") if request.date_from else "start"
    date_to_str = request.date_to.strftime("%Y%m%d") if request.date_to else date.today().strftime("%Y%m%d")
    filename = f"DATEV_Buchungsstapel_{date_from_str}_{date_to_str}.csv"

    # Log the export to database
    service = DatevExportService(database)
    service.log_export(
        user_id=user.id,
        config=request.config,
        export_response=export,
        date_from=request.date_from,
        date_to=request.date_to,
        filename=filename,
        export_format="csv",
    )

    # Audit log for security monitoring
    from app.services.audit import log_datev_export

    log_datev_export(
        user_id=user.id,
        transaction_count=export.transaction_count,
        date_range=(
            (request.date_from.isoformat(), request.date_to.isoformat() if request.date_to else date.today().isoformat())
            if request.date_from
            else None
        ),
    )

    return PlainTextResponse(
        content=export.csv_content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/datev/download/zip")
def export_datev_download_zip(
    request: DatevZipExportRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> StreamingResponse:
    """Generate and download DATEV ZIP with Buchungsstapel CSV and Belegbilder.

    Returns a ZIP file containing:
    - EXTF_Buchungsstapel.csv (booking data)
    - DATEV_Rechnungsausgang_YYYYMMDD_bis_YYYYMMDD.zip (revenue receipts with document.xml)
    - DATEV_Rechnungseingang_YYYYMMDD_bis_YYYYMMDD.zip (expense receipts with document.xml)

    The nested ZIPs should NOT be unpacked - DATEV Belegtransfer expects them as ZIP files.
    """
    import io

    from app.services.audit import log_datev_export

    service = DatevExportService(database)
    zip_export = service.export_zip(
        config=request.config,
        date_from=request.date_from,
        date_to=request.date_to,
        include_receipts=request.include_receipts,
        finalized_only=request.finalized_only,
        document_types=request.document_types,
    )

    # Log the export to database (using CSV export response for logging)
    csv_export = service.export(
        config=request.config,
        date_from=request.date_from,
        date_to=request.date_to,
    )
    service.log_export(
        user_id=user.id,
        config=request.config,
        export_response=csv_export,
        date_from=request.date_from,
        date_to=request.date_to,
        filename=zip_export.filename,
        export_format="zip",
    )

    # Audit log
    log_datev_export(
        user_id=user.id,
        transaction_count=zip_export.transaction_count,
        date_range=(
            (request.date_from.isoformat(), request.date_to.isoformat() if request.date_to else date.today().isoformat())
            if request.date_from
            else None
        ),
    )

    return StreamingResponse(
        io.BytesIO(zip_export.zip_content),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_export.filename}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(zip_export.zip_size_bytes),
        },
    )


@router.get("/datev/preview", response_model=DatevExportResponse)
def preview_datev_export(
    beraternummer: str = Query(..., description="Consultant number (7 digits)"),
    mandantennummer: str = Query(..., description="Client number (5 digits)"),
    wirtschaftsjahr_beginn: date = Query(..., description="Fiscal year start (YYYY-MM-DD)"),
    date_from: date | None = Query(None, description="Export from date"),
    date_to: date | None = Query(None, description="Export to date"),
    include_unreconciled: bool = Query(False, description="Include matched (not just reconciled)"),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> DatevExportResponse:
    """Preview DATEV export with query parameters.

    Useful for testing/previewing without sending full request body.
    """
    config = DatevConfig(
        beraternummer=beraternummer,
        mandantennummer=mandantennummer,
        wirtschaftsjahr_beginn=wirtschaftsjahr_beginn,
    )
    service = DatevExportService(database)
    return service.export(
        config=config,
        date_from=date_from,
        date_to=date_to,
        include_unreconciled=include_unreconciled,
    )


@router.post("/datev/validate", response_model=DatevValidationResult)
def validate_datev_export(
    request: DatevExportRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> DatevValidationResult:
    """Validate DATEV export format before download.

    Returns validation result with errors and warnings.
    """
    export = _run_export(database, request)
    return DatevExportService(database).validate(export)


@router.post("/datev/validate/zip", response_model=DatevValidationResult)
def validate_datev_zip_export(
    request: DatevZipExportRequest,
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> DatevValidationResult:
    """Validate DATEV ZIP export before download.

    Returns validation result with warnings for:
    - Receipts without attached files (Belegbild fehlt)
    - ZIP size exceeding DATEV Document-Package limit (465 MB)
    """
    service = DatevExportService(database)
    return service.validate_zip(
        config=request.config,
        date_from=request.date_from,
        date_to=request.date_to,
    )


@router.get("/history", response_model=ExportHistoryResponse)
def get_export_history(
    pagination: PaginationParams = Depends(),
    export_type: str | None = Query(None, description="Filter by export type (e.g., 'datev')"),
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> ExportHistoryResponse:
    """Get export history."""
    from app.services.response_builders import build_export_log_response

    query = select(ExportLog)

    if export_type:
        query = query.where(ExportLog.export_type == export_type)

    # Order by most recent first
    query = query.order_by(ExportLog.created_at.desc(), ExportLog.id.desc())

    items, total = paginate_query(database, query, pagination)

    return ExportHistoryResponse(
        items=[build_export_log_response(log) for log in items],
        total=total,
    )
