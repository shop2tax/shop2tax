"""PayPal Transaction Search API client.

Uses OAuth2 client credentials for authentication.
Fetches balance-affecting transaction records via the Reporting API.
"""

import base64
import logging
from datetime import datetime, timedelta

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

PAYPAL_LIVE_BASE = "https://api-m.paypal.com"
PAYPAL_SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
MAX_DATE_RANGE_DAYS = 31
REQUEST_TIMEOUT_SECONDS = 30
PAGE_SIZE = 500


class PayPalApiError(Exception):
    """Raised when the PayPal API returns an error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _get_base_url() -> str:
    """Return PayPal API base URL based on sandbox setting."""
    settings = get_settings()
    return PAYPAL_SANDBOX_BASE if settings.paypal_sandbox else PAYPAL_LIVE_BASE


def _get_access_token() -> str:
    """Authenticate via OAuth2 client credentials and return access token."""
    settings = get_settings()
    if not settings.paypal_client_id or not settings.paypal_client_secret:
        raise PayPalApiError("PayPal credentials not configured")

    credentials = base64.b64encode(f"{settings.paypal_client_id}:{settings.paypal_client_secret}".encode()).decode()

    response = httpx.post(
        f"{_get_base_url()}/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code != 200:
        raise PayPalApiError(
            f"PayPal authentication failed: {response.status_code}",
            status_code=response.status_code,
        )

    data = response.json()
    return data["access_token"]


RETRY_DELAYS = [1.0, 2.0, 4.0]


def fetch_transactions(
    access_token: str,
    start_date: datetime,
    end_date: datetime,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> dict:
    """Fetch a single page of transactions from PayPal.

    Retries on 429 (rate limit) and 5xx (server errors) with backoff: 1s, 2s, 4s.
    Returns the raw API response dict with transaction_details, total_items, total_pages, page.
    """
    import time

    last_error: Exception | None = None

    for attempt in range(3):
        try:
            response = httpx.get(
                f"{_get_base_url()}/v1/reporting/transactions",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "start_date": start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end_date": end_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "fields": "all",
                    "page_size": page_size,
                    "page": page,
                    "balance_affecting_records_only": "Y",
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = PayPalApiError(
                        f"PayPal transaction search failed: {response.status_code} - {response.text[:200]}",
                        status_code=response.status_code,
                    )
                    if attempt < 2:
                        delay = RETRY_DELAYS[attempt]
                        logger.warning("PayPal API %d on attempt %d, retrying in %gs", response.status_code, attempt + 1, delay)
                        time.sleep(delay)
                        continue
                raise PayPalApiError(
                    f"PayPal transaction search failed: {response.status_code} - {response.text[:200]}",
                    status_code=response.status_code,
                )
            return response.json()
        except httpx.TimeoutException as error:
            last_error = error
            if attempt < 2:
                delay = RETRY_DELAYS[attempt]
                logger.warning("PayPal API timeout on attempt %d, retrying in %gs", attempt + 1, delay)
                time.sleep(delay)
                continue
            raise

    if last_error:
        raise last_error
    msg = "PayPal API request failed after retries"
    raise RuntimeError(msg)


def _split_date_range(start_date: datetime, end_date: datetime) -> list[tuple[datetime, datetime]]:
    """Split a date range into chunks of MAX_DATE_RANGE_DAYS or less.

    PayPal API limits queries to 31 days per request.
    """
    chunks = []
    current_start = start_date
    while current_start < end_date:
        chunk_end = min(current_start + timedelta(days=MAX_DATE_RANGE_DAYS), end_date)
        chunks.append((current_start, chunk_end))
        current_start = chunk_end
    return chunks


def fetch_all_transactions(start_date: datetime, end_date: datetime) -> list[dict]:
    """Fetch all transactions for a date range, handling pagination and >31 day splits.

    Returns a flat list of transaction detail dicts.
    """
    access_token = _get_access_token()
    all_transactions: list[dict] = []

    for chunk_start, chunk_end in _split_date_range(start_date, end_date):
        page = 1
        while True:
            data = fetch_transactions(access_token, chunk_start, chunk_end, page=page)
            transactions = data.get("transaction_details", [])
            all_transactions.extend(transactions)

            total_pages = data.get("total_pages", 1)
            logger.info(
                "PayPal fetch: page %d/%d for %s to %s (%d transactions)",
                page,
                total_pages,
                chunk_start.date(),
                chunk_end.date(),
                len(transactions),
            )

            if page >= total_pages:
                break
            page += 1

    return all_transactions
