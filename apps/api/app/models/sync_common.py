"""Shared sync types used by Billbee and PayPal sync services."""

from dataclasses import dataclass, field


@dataclass
class SyncResult:
    """Result of a sync operation (Billbee or PayPal).

    fee_count: PayPal-specific (fee transactions imported); 0 for Billbee.
    sync_log_id: PayPal sets this to the created log ID; Billbee doesn't use it.
    pdf_count: Billbee-specific (PDFs successfully attached); 0 for PayPal.
    pdf_error_count: Billbee-specific (PDF fetch/storage failures); 0 for PayPal.
    """

    fetched_count: int = 0
    imported_count: int = 0
    skipped_count: int = 0
    fee_count: int = 0
    pdf_count: int = 0
    pdf_error_count: int = 0
    sync_log_id: str | None = None
    errors: list[str] = field(default_factory=list)
