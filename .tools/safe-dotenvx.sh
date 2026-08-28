#!/bin/bash
# dotenvx wrapper for safe environment loading
#
# Usage:
#   ./.tools/safe-dotenvx.sh local <command>   # Load .env
#
# Requires:
#   - @dotenvx/dotenvx installed (pnpm add -D @dotenvx/dotenvx)
#   - .env.keys file with decryption keys

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

ENV_TYPE="${1:-local}"
shift || true

# Determine which .env files to use
case "$ENV_TYPE" in
  local)
    if [ -f "$PROJECT_ROOT/.env.local" ]; then
      ENV_FILES="-f $PROJECT_ROOT/.env -f $PROJECT_ROOT/.env.local"
    else
      ENV_FILES="-f $PROJECT_ROOT/.env"
    fi
    ;;
  prod|production)
    ENV_FILES="-f $PROJECT_ROOT/.env"
    ;;
  *)
    echo "Usage: $0 <local|prod> <command>"
    exit 1
    ;;
esac

# Check if dotenvx is available
if ! command -v pnpx &> /dev/null; then
  echo "❌ pnpx not found. Install pnpm first."
  exit 1
fi

# Check for .env.keys
if [ ! -f "$PROJECT_ROOT/.env.keys" ]; then
  echo "⚠️  No .env.keys found. Running without dotenvx."
  echo "   (maintainer only — contributors do not need it)"
  exec "$@"
fi

# Check if .env file exists
if [ ! -f "$PROJECT_ROOT/.env" ]; then
  echo "⚠️  No .env found. Running without dotenvx."
  exec "$@"
fi

# Run command with dotenvx (--overload ensures project .env wins over global env vars)
exec pnpx @dotenvx/dotenvx run --overload $ENV_FILES -- "$@"
