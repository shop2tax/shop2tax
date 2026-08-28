#!/bin/sh
# Map env var names: Nuxt modules expect different names than our standard env vars.
# OAuth vars are optional — omitting them enables Local Mode (no login required).
# All values come from the container environment, never from files in the image.
[ -n "$SESSION_SECRET" ] && export NUXT_SESSION_PASSWORD="$SESSION_SECRET"
[ -n "$GOOGLE_CLIENT_ID" ] && export NUXT_OAUTH_GOOGLE_CLIENT_ID="$GOOGLE_CLIENT_ID"
[ -n "$GOOGLE_CLIENT_SECRET" ] && export NUXT_OAUTH_GOOGLE_CLIENT_SECRET="$GOOGLE_CLIENT_SECRET"
export NUXT_API_URL="$API_URL"
exec "$@"
