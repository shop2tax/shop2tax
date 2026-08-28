"""shop2tax FastAPI application."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from app.config import get_settings
from app.core.rate_limit import limiter
from app.database import get_db, get_engine
from app.routers import (
    accounts_router,
    csv_router,
    dashboard_router,
    export_router,
    mappings_router,
    oms_router,
    paypal_router,
    receipts_router,
    settings_router,
    sources_router,
    tags_router,
    transactions_router,
)


def _sanitize_proxy_env() -> None:
    """Drop IPv6-CIDR entries from NO_PROXY that httpx cannot parse.

    OrbStack/Docker inject a NO_PROXY containing IPv6 CIDRs (e.g. ``fd07::/64``)
    that crash ``httpx.AsyncClient()`` construction ("Invalid port"). This breaks
    every outbound HTTP call (Billbee, PayPal). Strip those entries so httpx can
    build clients; valid proxy/no-proxy entries are preserved.
    """
    for variable in ("NO_PROXY", "no_proxy"):
        value = os.environ.get(variable)
        if not value:
            continue
        cleaned = ",".join(entry for entry in value.split(",") if "::" not in entry)
        if cleaned != value:
            os.environ[variable] = cleaned


_sanitize_proxy_env()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup validation and cleanup."""
    try:
        await _startup()
    except Exception:
        import sys
        import traceback

        print("=" * 60, file=sys.stderr)
        print("STARTUP FAILED", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        sys.stderr.flush()
        raise

    yield


async def _startup() -> None:
    """Run all startup tasks. Extracted so lifespan can log exceptions."""
    settings = get_settings()

    # Validate required environment variables
    required_variables = ["DATABASE_URL"]
    missing = [variable for variable in required_variables if not os.environ.get(variable)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    # Verify database connection
    engine = get_engine()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    # Run migrations before seeding (skipped in tests — schema created via create_all)
    if not os.environ.get("SKIP_ALEMBIC_IN_TESTS"):
        from pathlib import Path

        from alembic import command
        from alembic.config import Config

        api_dir = Path(__file__).resolve().parent.parent
        alembic_config = Config(str(api_dir / "alembic.ini"))
        alembic_config.set_main_option("script_location", str(api_dir / "alembic"))

        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(alembic_config)
        heads = script.get_heads()
        if len(heads) > 1:
            print(f"Multiple alembic heads detected ({len(heads)}) — merging...")
            command.merge(alembic_config, "heads", message="auto_merge")

        command.upgrade(alembic_config, "head")

    # Seed data on startup (skipped in tests — seeded_session fixture handles it)
    if not os.environ.get("SKIP_ALEMBIC_IN_TESTS"):
        from app.database import get_session_local
        from app.seed import seed_oms_providers, seed_site_settings, seed_skr03_accounts, seed_system_sources, seed_system_user

        session = get_session_local()()
        try:
            inserted = seed_skr03_accounts(session)
            if inserted > 0:
                print(f"Seeded {inserted} SKR03 accounts")
            if seed_site_settings(session):
                print("Seeded SiteSettings row")
            if seed_system_user(session):
                print("Seeded system user for Local Mode")
            sources_inserted = seed_system_sources(session)
            if sources_inserted > 0:
                print(f"Seeded {sources_inserted} system sources")
            if seed_oms_providers(session):
                print("Billbee provider auto-configured from environment")
        finally:
            session.close()

    # Validate storage backend (skip in tests)
    if not os.environ.get("SKIP_ALEMBIC_IN_TESTS"):
        from app.services.storage_backend import get_storage_backend

        backend = get_storage_backend()
        backend.validate()

        # Generic WORM enforcement (D6): check property, not backend name
        if settings.environment.lower() == "production" and not backend.supports_worm:
            raise RuntimeError(
                f"Storage backend '{settings.storage_backend}' does not support WORM. Production requires WORM-capable storage for GoBD compliance."
            )

    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn)


app = FastAPI(title="shop2tax", version="0.1.0", lifespan=lifespan)

# Rate limiting setup
app.state.limiter = limiter


@app.exception_handler(429)
async def rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle rate limit exceeded errors with Retry-After header."""
    from slowapi.util import get_remote_address

    from app.services.audit import log_rate_limit_exceeded

    log_rate_limit_exceeded(
        ip_address=get_remote_address(request),
        endpoint=request.url.path,
        limit="exceeded",
    )

    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please slow down."},
        headers={"Retry-After": "60"},
    )


# Register routers
app.include_router(accounts_router)
app.include_router(oms_router)
app.include_router(dashboard_router)
app.include_router(csv_router)
app.include_router(export_router)
app.include_router(mappings_router)
app.include_router(paypal_router)
app.include_router(receipts_router)
app.include_router(settings_router)
app.include_router(sources_router)
app.include_router(tags_router)
app.include_router(transactions_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe for Docker healthcheck."""
    return {"status": "ok"}


@app.get("/api/ready")
def ready(database: Session = Depends(get_db)) -> dict[str, str]:
    """Readiness probe — checks database connectivity."""
    database.execute(text("SELECT 1"))
    return {"status": "ready"}
