MAKEFLAGS += --no-print-directory

# tokf: token-compressed output for AI coding (falls back to /bin/sh)
SHELL := $(shell command -v tokf 2>/dev/null || echo /bin/sh)

.DEFAULT_GOAL := help

# dotenvx wrapper
localenv = $(CURDIR)/.tools/safe-dotenvx.sh local

# Dev override (dev images, hot reload) layered onto the user-facing base stack.
# Explicit -f flags (e.g. make build) still take precedence.
export COMPOSE_FILE := docker-compose.yml:docker-compose.dev.yml

# ═══════════════════════════════════════════════════════════════════════════════
# Help (auto-generated from ##@Category comments)
# ═══════════════════════════════════════════════════════════════════════════════

help: ##@Help Show this help
	@echo "         __               ___   __            "
	@echo "   _____/ /_  ____  ____ |__ \\ / /_____ __  __"
	@echo "  / ___/ __ \\/ __ \\/ __ \\__/ // __/ __ \`/ |/_/"
	@echo " (__  ) / / / /_/ / /_/ / __// /_/ /_/ />  <  "
	@echo "/____/_/ /_/\\____/ .___/____/\\__/\\__,_/_/|_|  "
	@echo "                /_/"
	@echo ""
	@awk 'BEGIN {FS = ":.*##@"; printf "\nUsage: make [target]\n"} \
		/^[a-zA-Z_-]+:.*##@/ { \
			split($$2, a, " "); \
			category = a[1]; \
			desc = substr($$2, length(a[1])+2); \
			if (category != prev) { \
				printf "\n\033[1m%s:\033[0m\n", category; \
				prev = category \
			} \
			printf "  \033[36m%-18s\033[0m %s\n", $$1, desc \
		}' $(MAKEFILE_LIST)

# ═══════════════════════════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════════════════════════

doctor: ##@Setup Check prerequisites
	@echo "Checking prerequisites..."
	@printf "  Docker:         " && (command -v docker >/dev/null 2>&1 && printf '\033[32mOK\033[0m %s\n' "$$(docker --version | cut -d' ' -f3 | tr -d ',')" || printf '\033[31mMISSING\033[0m\n')
	@printf "  Docker Compose: " && (docker compose version >/dev/null 2>&1 && printf '\033[32mOK\033[0m %s\n' "$$(docker compose version --short)" || printf '\033[31mMISSING\033[0m\n')
	@printf "  uv:             " && (command -v uv >/dev/null 2>&1 && printf '\033[32mOK\033[0m %s\n' "$$(uv --version | cut -d' ' -f2)" || printf '\033[31mMISSING\033[0m\n')
	@printf "  pnpm:           " && (command -v pnpm >/dev/null 2>&1 && printf '\033[32mOK\033[0m %s\n' "$$(pnpm --version)" || printf '\033[31mMISSING\033[0m\n')
	@printf "  pre-commit:     " && (command -v pre-commit >/dev/null 2>&1 && printf '\033[32mOK\033[0m %s\n' "$$(pre-commit --version | cut -d' ' -f2)" || echo "not installed")
	@printf "  .env.keys:      " && ([ -f .env.keys ] && printf '\033[32mOK\033[0m exists\n' || printf '\033[31mMISSING\033[0m (maintainer only)\n')

env-check: ##@Setup Verify dotenvx works
	@[ -f .env.keys ] || (printf '\033[31mMissing .env.keys (maintainer only)\033[0m\n' && exit 1)
	@$(localenv) echo "dotenvx working" 2>/dev/null || printf '\033[31mdotenvx not configured\033[0m\n'

setup: ##@Setup Complete setup (deps + hooks + env)
	@if [ -f .env.keys ]; then \
		$(localenv) echo "dotenvx working" >/dev/null 2>&1 && printf '\033[32m.env.keys found — dotenvx OK\033[0m\n' || printf '\033[33m.env.keys found but dotenvx not configured\033[0m\n'; \
	else \
		printf '\033[33mNo .env.keys (maintainer secrets) — continuing in Local Mode\033[0m\n'; \
	fi
	@echo "Installing pre-commit hooks..."
	@command -v pre-commit >/dev/null 2>&1 || (echo "Installing pre-commit..." && uv tool install pre-commit)
	@pre-commit install
	@pre-commit install --hook-type pre-push
	@pre-commit install --hook-type commit-msg
	@printf '\033[32mSetup complete. Run make dev to start.\033[0m\n'

# ═══════════════════════════════════════════════════════════════════════════════
# Development
# ═══════════════════════════════════════════════════════════════════════════════

dev: ##@Development Start all containers (DB + API + Web)
	$(localenv) docker compose up

dev-build: ##@Development Rebuild and start all containers
	$(localenv) docker compose up --build

down: ##@Development Stop all containers
	$(localenv) docker compose down

logs: ##@Development Tail container logs
	$(localenv) docker compose logs -f

logs-api: ##@Development Show last 100 API container log lines (SINCE=5m for time filter)
	$(localenv) docker compose logs --tail=$(or $(TAIL),100) $(if $(SINCE),--since $(SINCE)) api

# ═══════════════════════════════════════════════════════════════════════════════
# Database
# ═══════════════════════════════════════════════════════════════════════════════

migrate: ##@Database Run Alembic migrations (auto-merges branches)
	@HEADS=$$($(localenv) docker compose exec -T api uv run alembic heads 2>/dev/null | grep -c head); \
	if [ "$$HEADS" -gt 1 ]; then \
		printf '\033[33mMultiple heads detected — merging...\033[0m\n'; \
		$(localenv) docker compose exec api uv run alembic merge heads -m "auto_merge"; \
	fi
	$(localenv) docker compose exec api uv run alembic upgrade head

migrate-new: ##@Database Create new migration (MSG=description)
	$(localenv) docker compose exec api uv run alembic revision --autogenerate -m "$(MSG)"

db-shell: ##@Database Open PostgreSQL shell
	$(localenv) docker compose exec db sh -c 'PGPASSWORD="$$POSTGRES_PASSWORD" exec psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

db-query: ##@Database Run SQL query (SQL="SELECT ...")
	@$(localenv) docker compose exec -T db sh -c 'PGPASSWORD="$$POSTGRES_PASSWORD" psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "'"$(SQL)"'"'

db-backup: ##@Database Backup database to backups/
	@mkdir -p backups
	@$(localenv) docker compose exec -T db sh -c 'PGPASSWORD="$$POSTGRES_PASSWORD" pg_dump -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" --format=custom' > backups/shop2tax-$$(date +%Y%m%d-%H%M%S).dump
	@printf '\033[32mBackup saved to backups/%s\033[0m\n' "$$(ls -t backups/ | head -1)"

db-restore: ##@Database Restore database (FILE=backups/xxx.dump, FORCE=1 skips confirmation)
	@[ -n "$(FILE)" ] || (printf '\033[31mUsage: make db-restore FILE=backups/shop2tax-xxx.dump\033[0m\n' && exit 1)
	@[ -f "$(FILE)" ] || (printf '\033[31mFile not found: %s\033[0m\n' "$(FILE)" && exit 1)
	@printf '\033[31mWARNING: This will overwrite the current database!\033[0m\n'
	@if [ "$(FORCE)" != "1" ]; then printf "Continue? [y/N] "; read confirm; [ "$$confirm" = "y" ] || exit 1; fi
	@$(localenv) docker compose exec -T db sh -c 'PGPASSWORD="$$POSTGRES_PASSWORD" pg_restore -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" --clean --if-exists' < $(FILE)
	@printf '\033[32mDatabase restored from %s\033[0m\n' "$(FILE)"

db-reset: ##@Database Reset database (delete all data! FORCE=1 skips confirmation)
	@printf '\033[31mWARNING: This will delete all data!\033[0m\n'
	@if [ "$(FORCE)" != "1" ]; then printf "Continue? [y/N] "; read confirm; [ "$$confirm" = "y" ] || exit 1; fi
	$(localenv) docker compose down -v
	$(MAKE) dev

# ═══════════════════════════════════════════════════════════════════════════════
# Quality
# ═══════════════════════════════════════════════════════════════════════════════

lint: ##@Quality Fast lint (ruff + eslint)
	$(localenv) docker compose exec -T api uv run ruff check app/
	pnpm --dir apps/web lint

lint-fix: ##@Quality Lint with auto-fix
	$(localenv) docker compose exec -T api uv run ruff check --fix app/
	$(localenv) docker compose exec -T api uv run ruff format app/
	pnpm --dir apps/web lint:fix

typecheck: ##@Quality Type check (vue-tsc + ty)
	pnpm --dir apps/web typecheck
	$(localenv) docker compose exec -T api uv run ty check app

test: ##@Quality Run all tests (in Docker)
	$(localenv) docker compose exec api uv run pytest tests/ -v

test-file: ##@Quality Run specific test (FILE=tests/test_foo.py)
	$(localenv) docker compose exec api uv run pytest $(FILE) -v

test-web: ##@Quality Run frontend unit tests (vitest)
	pnpm --dir apps/web test

audit: ##@Quality Dependency vulnerability audit (pip-audit + pnpm audit)
	$(localenv) docker compose exec -T api sh -c "uv export --no-dev --no-emit-workspace --no-hashes -o /tmp/requirements-audit.txt && uv run pip-audit --disable-pip --no-deps -r /tmp/requirements-audit.txt"
	pnpm --dir apps/web audit --audit-level=high

check: lint typecheck build-web test-web test ##@Quality Full quality check (lint + typecheck + build + web/api tests)

# ═══════════════════════════════════════════════════════════════════════════════
# Build
# ═══════════════════════════════════════════════════════════════════════════════

build-web: ##@Build Build frontend (catches SSR/import errors)
	pnpm --dir apps/web build

build: ##@Build Build production images
	$(localenv) docker compose -f docker-compose.prod.yml build

# ═══════════════════════════════════════════════════════════════════════════════
# Container Exec
# ═══════════════════════════════════════════════════════════════════════════════

exec: ##@Development Run command in API container (CMD="python3 -c '...'")
	@[ -z "$(CMD)" ] && printf '\033[31mUsage: make exec CMD="python3 -c '\''...'\''"\033[0m\n' && exit 1 || true
	$(localenv) docker compose exec api uv run $(CMD)

api: ##@Development Call API endpoint (ENDPOINT="/api/health" METHOD=GET BODY='{"key":"val"}')
	@[ -z "$(ENDPOINT)" ] && printf '\033[31mUsage: make api ENDPOINT="/api/health" [METHOD=GET] [BODY='\''{"key":"val"}'\'']\033[0m\n' && exit 1 || true
	@$(localenv) docker compose exec -T api curl -s -X $(or $(METHOD),GET) -H "Content-Type: application/json" -H "X-Proxy-Secret: $${PROXY_SECRET}" -H "X-User-Id: 00000000-0000-0000-0000-000000000000" -H "X-User-Email: system@local" -H "X-User-Name: System" $(if $(BODY),-d '$(BODY)') "http://localhost:8000$(ENDPOINT)"

.PHONY: help doctor env-check setup dev dev-build down logs exec api
.PHONY: migrate migrate-new db-shell db-query db-backup db-restore db-reset
.PHONY: lint lint-fix typecheck test test-file check build-web build
