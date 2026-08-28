"""Dashboard router for aggregated metrics."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import GERMAN_MONTHS
from app.database import get_db
from app.deps import CurrentUser, get_current_user
from app.models.ai_extraction_log import AIExtractionLog

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


class ProviderCostSummary(BaseModel):
    """Cost breakdown for a single AI provider."""

    provider: str
    extraction_count: int
    total_cost_cents: float
    total_input_tokens: int
    total_output_tokens: int


class AICostResponse(BaseModel):
    """Aggregated AI extraction cost response."""

    total_extractions: int
    total_cost_cents: float
    by_provider: list[ProviderCostSummary]
    period_start: date
    period_end: date


@router.get("/ai-costs", response_model=AICostResponse)
def get_ai_costs(
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
    period_start: date | None = Query(None, description="Start of period (default: first day of current month)"),
    period_end: date | None = Query(None, description="End of period (default: today)"),
) -> AICostResponse:
    """Return aggregated AI extraction costs.

    Aggregates instance-wide (Shared Tenant — no user_id filter).
    Default period: current month.
    """
    today = date.today()
    start = period_start or today.replace(day=1)
    end = period_end or today

    # Deterministic providers (not AI) — exclude from KI-Erkennung stats
    non_ai_providers = {"zugferd"}

    # Base filter: created_at within period, only actual AI providers
    period_filter = [
        func.date(AIExtractionLog.created_at) >= start,
        func.date(AIExtractionLog.created_at) <= end,
        AIExtractionLog.source.notin_(non_ai_providers),
    ]

    # Per-provider breakdown
    provider_rows = database.execute(
        select(
            AIExtractionLog.source,
            func.count().label("extraction_count"),
            func.coalesce(func.sum(AIExtractionLog.cost_cents), 0).label("total_cost_cents"),
            func.coalesce(func.sum(AIExtractionLog.input_tokens), 0).label("total_input_tokens"),
            func.coalesce(func.sum(AIExtractionLog.output_tokens), 0).label("total_output_tokens"),
        )
        .where(*period_filter)
        .group_by(AIExtractionLog.source)
        .order_by(AIExtractionLog.source)
    ).all()

    by_provider = [
        ProviderCostSummary(
            provider=row.source,
            extraction_count=row.extraction_count,
            total_cost_cents=float(row.total_cost_cents),
            total_input_tokens=int(row.total_input_tokens),
            total_output_tokens=int(row.total_output_tokens),
        )
        for row in provider_rows
    ]

    total_extractions = sum(provider.extraction_count for provider in by_provider)
    total_cost_cents = sum(provider.total_cost_cents for provider in by_provider)

    return AICostResponse(
        total_extractions=total_extractions,
        total_cost_cents=total_cost_cents,
        by_provider=by_provider,
        period_start=start,
        period_end=end,
    )


# --- EÜR Summary ---


class EuerSummary(BaseModel):
    """Einnahmen-Überschuss-Rechnung (EÜR) summary.

    Follows official EÜR positions:
    - Revenue: Sum of REVENUE accounts (8xxx)
    - Operating expenses: Sum of EXPENSE accounts (3xxx, 4xxx)
    - §13b-USt (Zeile 58, Pos 186): RC tax owed to Finanzamt
    - §13b-VSt (Zeile 57, Pos 185): RC input tax (only for Regelbesteuert)

    NEUTRAL accounts (1xxx including 1590 Durchlaufende Posten) are excluded.
    """

    # Core EÜR values
    revenue_total: Decimal  # Sum of REVENUE category line items
    expense_total: Decimal  # Sum of EXPENSE category line items (without RC tax)

    # §13b Reverse Charge (separate EÜR positions)
    rc_tax_owed: Decimal  # Zeile 58, Pos 186 — USt ans FA (all RC items)
    rc_input_tax: Decimal  # Zeile 57, Pos 185 — absetzbare VSt (only Regelbesteuert)

    # Calculated values
    profit_before_rc: Decimal  # revenue_total - expense_total
    profit: Decimal  # profit_before_rc - rc_tax_owed + rc_input_tax

    # Metadata
    is_small_business: bool  # Kleinunternehmer — affects rc_input_tax (always 0)
    period_start: date
    period_end: date
    period_label: str | None  # Human-readable period (e.g., "Januar 2026")


@router.get("/euer-summary", response_model=EuerSummary)
def get_euer_summary(
    user: CurrentUser = Depends(get_current_user),
    database: Session = Depends(get_db),
    period_start: date | None = Query(None, description="Start of period (default: start of current year)"),
    period_end: date | None = Query(None, description="End of period (default: today)"),
) -> EuerSummary:
    """Calculate EÜR (Einnahmen-Überschuss-Rechnung) summary for a period.

    This is a simplified EÜR calculation based on ReceiptLineItems:
    - Revenue = Sum of line items on REVENUE accounts (8xxx)
    - Expenses = Sum of line items on EXPENSE accounts (3xxx, 4xxx)
    - §13b-USt = RC tax owed to Finanzamt (Zeile 58)
    - §13b-VSt = RC input tax, only for Regelbesteuert (Zeile 57)

    NEUTRAL accounts (1xxx including 1590 Durchlaufende Posten) are excluded
    from revenue and expense calculations.

    For Kleinunternehmer: §13b-USt is a real cost (no input tax offset).
    For Regelbesteuert: §13b-USt ≈ §13b-VSt (neutralizes).
    """
    from decimal import Decimal

    from sqlalchemy.orm import joinedload

    from app.models.receipt import Receipt
    from app.models.receipt_line_item import ReceiptLineItem
    from app.models.site_settings import SiteSettings
    from app.models.skr03 import AccountCategory

    today = date.today()
    start = period_start or today.replace(month=1, day=1)  # Default: start of year
    end = period_end or today

    # Get Kleinunternehmer status
    site_settings = database.execute(select(SiteSettings).limit(1)).scalar_one_or_none()
    is_small_business = bool(site_settings.is_small_business) if site_settings and site_settings.is_small_business else False

    # Query all line items with their SKR03 accounts for the period
    query = (
        select(ReceiptLineItem)
        .join(Receipt)
        .options(joinedload(ReceiptLineItem.skr03_account))
        .where(
            Receipt.deleted_at.is_(None),
            Receipt.date >= start,
            Receipt.date <= end,
        )
    )
    line_items = database.execute(query).scalars().unique().all()

    # Calculate totals by category
    revenue_total = Decimal("0.00")
    expense_total = Decimal("0.00")
    rc_tax_owed = Decimal("0.00")
    rc_input_tax = Decimal("0.00")

    for item in line_items:
        # Skip items without SKR03 account (shouldn't happen, but be safe)
        if not item.skr03_account:
            continue

        category = item.skr03_account.category

        # Skip NEUTRAL accounts (1590 Durchlaufende Posten, bank accounts, etc.)
        if category == AccountCategory.NEUTRAL:
            continue

        amount = item.amount

        # Add to appropriate category
        if category == AccountCategory.REVENUE:
            revenue_total += amount
        elif category == AccountCategory.EXPENSE:
            expense_total += abs(amount)  # Expenses stored as positive

        # Calculate RC tax (separate from regular expense)
        if item.tax_rule.is_reverse_charge():
            rc_amount = item.reverse_charge_tax_amount or Decimal("0.00")
            rc_tax_owed += rc_amount
            if item.tax_rule.has_input_tax():
                rc_input_tax += rc_amount

    # Kleinunternehmer cannot claim input tax
    if is_small_business:
        rc_input_tax = Decimal("0.00")

    # Calculate profit
    profit_before_rc = revenue_total - expense_total
    profit = profit_before_rc - rc_tax_owed + rc_input_tax

    # Generate period label

    if start.month == end.month and start.year == end.year:
        period_label = f"{GERMAN_MONTHS[start.month - 1]} {start.year}"
    elif start.year == end.year:
        period_label = f"{GERMAN_MONTHS[start.month - 1]} – {GERMAN_MONTHS[end.month - 1]} {start.year}"
    else:
        period_label = f"{GERMAN_MONTHS[start.month - 1]} {start.year} – {GERMAN_MONTHS[end.month - 1]} {end.year}"

    return EuerSummary(
        revenue_total=revenue_total,
        expense_total=expense_total,
        rc_tax_owed=rc_tax_owed,
        rc_input_tax=rc_input_tax,
        profit_before_rc=profit_before_rc,
        profit=profit,
        is_small_business=is_small_business,
        period_start=start,
        period_end=end,
        period_label=period_label,
    )
