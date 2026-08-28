"""Rate limiting configuration.

Keys are derived from ``request.client.host``. In production uvicorn runs with
``--proxy-headers`` and trusts only the internal network, so the value is the real
client IP as forwarded by the Nuxt proxy / Caddy; spoofed X-Forwarded-For headers
from outside the internal network are ignored by uvicorn itself.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Rate limit constants
RATE_LIMIT_CSV_UPLOAD = "10/minute"  # CSV upload/parse
RATE_LIMIT_CREDENTIALS = "5/minute"  # Sensitive credential operations
RATE_LIMIT_GENERAL = "60/minute"  # General API endpoints


def get_extraction_rate_limit() -> str:
    """Get extraction rate limit from config (shared tenant = global counter)."""
    from app.config import get_settings

    return get_settings().extraction_rate_limit


def global_rate_limit_key(request: Request) -> str:
    """Return a fixed key for instance-wide (global) rate limiting."""
    return "global"
