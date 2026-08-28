# syntax=docker/dockerfile:1
# check=error=true
#
# Nuxt frontend. Targets:
#   development — pnpm dev with hot reload (docker-compose.dev.yml)
#   production  — node + the built .output bundle, nothing else (docker-compose.yml)
#
# Build context is the repo root.

ARG NODE_VERSION=22
ARG PNPM_VERSION=11.5.2

# ── development ──────────────────────────────────────────────────────────────
FROM node:${NODE_VERSION}-slim AS development
ARG PNPM_VERSION
ENV NODE_ENV=development \
    TZ=Europe/Berlin
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate
WORKDIR /app
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
# --ignore-scripts: postinstall runs `nuxt prepare`, which needs the sources; `pnpm dev` prepares anyway.
RUN pnpm install --frozen-lockfile --ignore-scripts
COPY apps/web ./
EXPOSE 3000
CMD ["pnpm", "dev", "--host", "0.0.0.0"]

# ── build: install deps, build the self-contained server bundle ──────────────
FROM node:${NODE_VERSION}-slim AS build
ARG PNPM_VERSION
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate
WORKDIR /app
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile --ignore-scripts
COPY apps/web ./
# NODE_ENV=production during build also turns on vue-tsc (nuxt.config typeCheck).
ENV NODE_ENV=production
RUN pnpm build

# ── production: runtime image ────────────────────────────────────────────────
FROM node:${NODE_VERSION}-slim AS production
ENV NODE_ENV=production \
    TZ=Europe/Berlin
# curl for the compose healthcheck, ca-certificates for outbound HTTPS (Google OAuth)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Entrypoint maps env var names for Nuxt modules
COPY --chown=node:node apps/web/entrypoint.sh ./entrypoint.sh
COPY --from=build --chown=node:node /app/.output ./.output
USER node
EXPOSE 3000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["node", ".output/server/index.mjs"]
