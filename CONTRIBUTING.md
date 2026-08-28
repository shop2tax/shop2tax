# Contributing to shop2tax

Thank you for your interest in contributing to shop2tax!

## Getting Started

### Prerequisites

- Docker + Docker Compose (everything runs in containers — no local Python/Node needed)
- Optional, only to run lint/typecheck outside Docker: [uv](https://docs.astral.sh/uv/) (Python) and [pnpm](https://pnpm.io/) (Node). The pinned versions live in `mise.toml` — with [mise](https://mise.jdx.dev/) a single `mise install` sets them up.

You do **not** need Google OAuth credentials, cloud storage, or any secrets to develop. The
app runs in **Local Mode** by default (see below).

### Setup (Local Mode — recommended for contributors)

```bash
# Copy the environment template — it works as-is: no login, local file storage
cp .env.example .env

# Start everything (DB + API + Web)
make dev
```

Open `http://127.0.0.1:3002` (not `localhost` — macOS DNS issue).

**Local Mode** means the app starts without authentication: no Google OAuth, no proxy
secret, no cloud credentials. A system user is injected automatically. This is the default
when `GOOGLE_CLIENT_ID` is left empty in `.env` (it already is in `.env.example`).

Install the git hooks (recommended before opening a PR):

```bash
make setup
```

> `make setup` installs the pre-commit hooks. It works without `.env.keys` — that file (and
> the `dotenvx` workflow) is only for **maintainers**, who keep an encrypted `.env` locally.
> No env file is committed. Contributors use a plain `.env` (created by `./install.sh` or
> `cp .env.example .env`) and can ignore all of this.

## Development Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Make your changes
4. Run quality checks: `make check` (lint + typecheck + build + test)
5. Commit using conventional commits (see below)
6. Open a pull request

## Code Style

- **All code in English.** German domain terms are translated (Transaction, not Buchung).
- **Backend**: Python 3.12, formatted with [ruff](https://docs.astral.sh/ruff/)
- **Frontend**: TypeScript, formatted with ESLint
- Run `make lint-fix` to auto-fix formatting issues

## Commit Convention

```
feat(api): add CSV upload endpoint
fix(web): correct date parsing
refactor(api): simplify pagination logic
```

Scopes: `api`, `web`, `docker`, `deps`, `plan`. Enforced by commitlint.

## Running Tests

```bash
make test                              # All tests (Docker)
make test-file FILE=tests/test_csv.py  # Single file
```

Tests require Docker (PostgreSQL).

## Pull Request Guidelines

- Keep PRs focused — one feature or fix per PR
- Include tests for new functionality
- Ensure `make check` passes before submitting
- Update documentation if behavior changes

## Questions?

Open an issue for questions or discussion.
