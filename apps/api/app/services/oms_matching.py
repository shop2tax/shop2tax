"""Provider-agnostic matching of transactions to OMS orders (D-5).

Operates purely on generic OmsOrder fields (amount, date, name, order_number,
email) so it works for any provider. Order-number normalization (Shopify "#"
prefix stripping) is an order_number pattern, not Billbee-specific.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.services.oms_provider import OmsOrder


@dataclass
class OmsMatchSuggestion:
    """Suggested OMS order match for a transaction."""

    oms_order_id: str
    order_number: str
    confidence: float  # 0.0 - 1.0
    match_reasons: list[str]
    order_amount: Decimal
    order_date: datetime
    customer_name: str


@dataclass
class OmsMatchResult:
    """Result of bulk OMS matching."""

    matched_count: int
    unmatched_count: int
    matched_transaction_ids: list[str]


def find_matching_orders(
    orders: list[OmsOrder],
    amount: Decimal,
    transaction_date: datetime,
    counterparty: str | None = None,
    date_tolerance_days: int = 7,
) -> list[OmsMatchSuggestion]:
    """Find OMS orders that might match a transaction.

    Matching criteria:
    - Exact amount match (highest confidence)
    - Date within tolerance window
    - Counterparty name similarity (if provided)

    Returns suggestions sorted by confidence descending.
    """
    suggestions: list[OmsMatchSuggestion] = []

    for order in orders:
        reasons: list[str] = []
        confidence = 0.0

        # Amount matching (most important)
        amount_diff = abs(order.total_cost - abs(amount))
        if amount_diff == 0:
            reasons.append("Exact amount match")
            confidence += 0.5
        elif amount_diff < Decimal("0.10"):
            reasons.append(f"Amount within €0.10 (diff: €{amount_diff})")
            confidence += 0.3

        # Date matching
        date_diff = abs((order.created_at.date() - transaction_date.date()).days)
        if date_diff == 0:
            reasons.append("Same date")
            confidence += 0.3
        elif date_diff <= 3:
            reasons.append(f"Date within {date_diff} days")
            confidence += 0.2
        elif date_diff <= date_tolerance_days:
            reasons.append(f"Date within {date_diff} days")
            confidence += 0.1

        # Counterparty matching (simple substring check)
        if counterparty and order.customer_name:
            counterparty_lower = counterparty.lower()
            customer_lower = order.customer_name.lower()
            if counterparty_lower in customer_lower or customer_lower in counterparty_lower:
                reasons.append("Customer name matches counterparty")
                confidence += 0.2

        # Only include if there's some match
        if confidence > 0 and reasons:
            suggestions.append(
                OmsMatchSuggestion(
                    oms_order_id=order.order_id,
                    order_number=order.order_number,
                    confidence=min(confidence, 1.0),
                    match_reasons=reasons,
                    order_amount=order.total_cost,
                    order_date=order.created_at,
                    customer_name=order.customer_name,
                )
            )

    suggestions.sort(key=lambda suggestion: suggestion.confidence, reverse=True)
    return suggestions


def build_order_lookup(orders: list[OmsOrder]) -> tuple[dict[str, OmsOrder], dict[str, OmsOrder]]:
    """Build lookup dicts for fast matching.

    Stores both original and normalized order numbers (stripped "#" prefix) so that
    "3703" matches "#3703" and vice versa.

    Returns (order_number_lookup, customer_email_lookup).
    """
    by_order_number: dict[str, OmsOrder] = {}
    by_email: dict[str, OmsOrder] = {}

    for order in orders:
        if order.order_number:
            by_order_number[order.order_number] = order
            stripped = order.order_number.lstrip("#").strip()
            if stripped and stripped != order.order_number:
                by_order_number[stripped] = order
        if order.customer_email:
            by_email[order.customer_email.lower()] = order

    return by_order_number, by_email


def _extract_order_numbers(reference: str) -> list[str]:
    """Extract all possible order number candidates from a reference string.

    Marketplace CSVs use different formats for order references:
    - Etsy: "Payment for Order #3964911563" -> ["3964911563"]
    - Shopify: "#1234" -> ["1234"]
    - Amazon: "123-4567890-1234567" (no prefix, used as-is)
    - Multiple: "Payment for Order #111, Order #222" -> ["111", "222"]
    """
    cleaned = reference.strip()
    candidates: list[str] = []

    # Extract all "Order #XXXX" / "Bestellung #XXXX" patterns anywhere in string
    order_matches = re.findall(r"(?:Order|Bestellung)\s*#\s*(\S+)", cleaned, flags=re.IGNORECASE)
    candidates.extend(order_matches)

    # Extract standalone "#XXXX" (Shopify)
    hash_matches = re.findall(r"(?<!\w)#(\d+)", cleaned)
    candidates.extend(hash_matches)

    # If no patterns found, use the whole string stripped as fallback (Amazon format)
    if not candidates:
        candidates.append(cleaned)
        # For plain numbers (Shopify order_id = "3703"), also try with "#" prefix
        if cleaned.isdigit():
            candidates.append(f"#{cleaned}")

    return candidates


def match_transaction_to_order(
    order_number_lookup: dict[str, OmsOrder],
    email_lookup: dict[str, OmsOrder],
    match_strategy: str = "order_number",
    source_reference: str | None = None,
    counterparty: str | None = None,
) -> OmsOrder | None:
    """Match a single transaction to an OMS order.

    Matching strategy is configured per OmsStore:
    - order_number: source_reference -> order.order_number (Amazon, Etsy, Shopify)
    - email: counterparty -> order.customer_email (Stripe)
    """
    if match_strategy == "order_number" and source_reference:
        candidates = _extract_order_numbers(source_reference)
        for candidate in candidates:
            match = order_number_lookup.get(candidate)
            if match:
                return match
        return order_number_lookup.get(source_reference)

    if match_strategy == "email" and counterparty:
        return email_lookup.get(counterparty.lower())

    return None
