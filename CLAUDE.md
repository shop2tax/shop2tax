## What This Is

Open-source (AGPL-3.0) self-hosted bookkeeping for German Kleinunternehmer. CSV import (Amazon, Etsy, Shopify, Stripe + generic bank CSV) → Receipt management (GoBD-WORM) → SKR03 accounting → DATEV export for Steuerberater. Integrations: Billbee (order/receipt sync), PayPal (API sync).

Subsystem docs: `apps/api/CLAUDE.md`, `apps/web/CLAUDE.md`

## Commands

```bash
# Development
make dev              # Start all (DB + API + Web) via Docker
make dev-build        # Rebuild + start all containers
make down             # Stop containers
make logs             # Tail container logs
make doctor           # Check prerequisites (Docker, uv, pnpm, .env.keys)
make setup            # Install pre-commit hooks + verify env

# Quality (make check = all of these)
make check            # Full quality: lint + typecheck + build-web + test
make lint              # Fast lint (ruff + eslint), no auto-fix
make lint-fix         # Auto-fix ruff + eslint
make typecheck        # vue-tsc type check
make build-web        # Nuxt build (catches SSR/import errors)
make build            # Build production images
make test             # Run pytest in Docker
make test-file FILE=tests/test_csv.py  # Single test file in Docker

# Database
make migrate          # Run Alembic migrations (auto-merges heads)
make migrate-new MSG="description"  # Generate new migration
make db-shell         # PostgreSQL REPL
make db-query SQL="SELECT ..."  # Run SQL query
make db-backup        # Backup to backups/
make db-restore FILE=backups/xxx.dump  # Restore from backup
make db-reset         # Delete all data + restart (destructive! FORCE=1 skips prompt)

# Direct (no Docker, for local debugging)
uv run ruff check apps/api/
uv run pytest apps/api/tests/ -v
uv run pytest apps/api/tests/test_foo.py::should_bar -v
```

## Architecture

**Monorepo**: `apps/api/` (FastAPI, Python 3.12, UV) + `apps/web/` (Nuxt 4, Nuxt UI v4, pnpm)

**Everything runs in Docker** — no local Python/Node needed. Dev: port 3002 (host) → 3000 (container). Prod: Caddy (auto-SSL) → `docker-compose.prod.yml`. `docker-compose.yml` is the user-facing stack with production images (what `install.sh` runs, web bound to `127.0.0.1` only); `docker-compose.dev.yml` is the dev override (dev targets, hot reload, source mounts), layered automatically by the Makefile via `COMPOSE_FILE`.

**Shared Tenant**: All users of an instance see the same data. `user_id` remains as audit metadata (`created_by`), not as isolation filter.

**Two Auth Modes** (auto-detected via `GOOGLE_CLIENT_ID`):
- **Auth Mode**: `GOOGLE_CLIENT_ID` set → Google OAuth login required, proxy secret validated
- **Local Mode**: No OAuth credentials → no login, system user (`00000000-...`) injected automatically

**Request flow**: Browser → Nuxt (SSR + optional OAuth) → FastAPI (internal network only)
- Auth Mode: Nuxt middleware validates session, injects `X-User-*` + `X-Proxy-Secret` headers
- Local Mode: Nuxt middleware injects system-user headers, no session/proxy secret check
- FastAPI `deps.py:get_current_user()` returns system user in Local Mode, validates proxy secret in Auth Mode
- FastAPI is NOT publicly accessible — proxy secret prevents direct API access (Auth Mode only)

**Database**: PostgreSQL 16, SQLAlchemy 2.0 with `select()` style (not legacy Query API), Alembic migrations. Auto-migrates + seeds on API startup via lifespan.

## Code Language Rules

**All code in English.** German domain terms are translated:
- Transaction (not Buchung), AccountingPattern (not KontierungPattern), revenue/expense (not einnahmen/ausgaben)
- **Model/class names in English. UI labels in German.** DATEV CSV column headers stay German (spec compliance), but all code identifiers in English.
- **Exception**: SKR03 stays as-is (standard name). German account names in seed data fine.

## Commit Convention

```
feat(api): add CSV upload endpoint
fix(web): correct date parsing
```

Scopes: `api`, `web`, `docker`, `deps`, `plan`. Enforced by commitlint. Scopes are optional (`scope-empty: [0]`).

## Secrets

No env file is committed (`.env*` gitignored except `.env.example`). The maintainer keeps a dotenvx-encrypted `.env` locally with `.env.keys`; `make dev` uses the `localenv` wrapper to decrypt at runtime, and falls back to a plain `.env` when `.env.keys` is absent. Production images contain no env files — all runtime config comes from `environment:` in `docker-compose.prod.yml`.

## Gotchas

- **`localhost` doesn't resolve on macOS** — use `http://127.0.0.1:3002` in browser
- **Google OAuth redirect URI** must match exactly: `http://127.0.0.1:3002/auth/google` (Auth Mode only)
- **Local Mode** — remove/comment `GOOGLE_CLIENT_ID` from `.env` → app starts without login
- **`make check` includes `build-web`** — Nuxt build catches SSR/import errors that lint misses
- **Alembic multi-head** — `make migrate` auto-detects and merges multiple heads
- **GCS validation on startup** — Lifespan checks DSGVO location + GoBD retention policy
- **Finalized receipts are immutable** — GoBD compliance, no edits after finalization
- **`ENVIRONMENT=production` requires WORM storage (GCS)** — with `STORAGE_BACKEND=local` the API refuses to start, so the user-facing compose defaults to `development`

## Docs

- `docs/datev-export.md` — DATEV Buchungsstapel format specification

## Skills

| Context | Skill |
|---------|-------|
| Backend (apps/api/) | **shop2tax-api**, python-grandmaster, astral:ruff, astral:uv |
| Frontend (apps/web/) | **shop2tax-web**, nuxt-vue-tailwind-ui |
| Security | vibesec |
| Makefile | lia-makefile:makefile |
