# apps/api

FastAPI backend, Python 3.12, UV. For implementation patterns, code examples, and troubleshooting: use `shop2tax-api` skill.

## Key Directories

- `app/models/` — SQLAlchemy 2.0 declarative with `Mapped[]` type annotations
- `app/schemas/` — Pydantic request/response (oms, csv, datev, paypal, receipt, skr03, source, transaction)
- `app/routers/` — 11 routers: accounts, csv, dashboard, export, mappings, oms, paypal, receipts, settings, sources, tags, transactions
- `app/services/oms_provider.py` — OmsProvider Protocol + OmsOrder dataclasses + provider factory; `app/services/providers/billbee/` — Billbee implementation. `oms_matching.py` — provider-agnostic transaction↔order matching. `oms_sync.py` — provider-injected receipt sync.
- `app/services/` — 15 services, key ones: response_builders, receipt_service, storage_backend, gcs_backend, local_backend, generic_csv_parser, paypal_sync
- `app/core/` — pagination.py, rate_limit.py (slowapi)

## Key Patterns

- **Auth** — `deps.py:get_current_user()`. Fail-closed if `NUXT_PROXY_SECRET` not set.
- **Config** — `config.py` Pydantic Settings, cached via `get_settings()`.
- **Seed Data** — `seed.py` — 43 SKR03 accounts + SiteSettings, auto-seeded on startup.

## Testing

PostgreSQL (separate `shop2tax_test` DB, created/dropped per session). Requires Docker (`make test`).
Test names: `should_parse_csv_with_custom_mapping` (not `test_parse_csv...`).

## Integrations

OMS providers (order/receipt sync via pluggable `OmsProvider`; Billbee is the first implementation), PayPal (REST API sync), Google Cloud Storage (GoBD-WORM), Sentry (optional, `SENTRY_DSN`)

## CSV Parsers

**Marketplace parsers** (dedicated, fixed formats):
- `etsy_parser.py` — Etsy Payment Account Statement. Fees are separate rows. 13 transaction types.
- `shopify_parser.py` — Shopify Payment Transactions export. Fees are columns per row. 6 transaction types.

**Shared utilities** (`csv_utils.py`):
- `sniff_encoding()` — UTF-8/BOM/Windows-1252 detection
- `sniff_delimiter()` — comma/semicolon/tab
- `parse_money()` — German/English formats, currency symbols
- `parse_localized_date()` — German/English month names, ISO, localized

**Generic parser** (`generic_csv_parser.py`):
- Bank CSVs with user-configurable column mapping via `CsvMappingProfile`

## Gotchas

- **`database.py` uses lazy engine init** — avoids import-time DB connections, important for tests
- **Lifespan auto-migrates** — `main.py` runs `alembic upgrade head` on every startup
- **Lifespan validates GCS** — Checks DSGVO location + retention policy on startup
- **Sentry scrubs secrets** — `main.py` inits Sentry with a `before_send` hook that redacts the `x-proxy-secret`/`x-user-*` request headers, plus `include_local_variables=False` and `send_default_pii=False`. Do not remove these — they keep `NUXT_PROXY_SECRET` and PII out of error events (covered by `tests/test_sentry_scrub.py`).
