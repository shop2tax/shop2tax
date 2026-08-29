# apps/web

Nuxt 4 + Nuxt UI v4 frontend. For implementation patterns, UI rules, and troubleshooting: use `shop2tax-web` skill.

## Key Directories

- `app/pages/` — File-based routing: index (dashboard), transactions, receipts/ (3 pages), import, export, settings, login
- `app/components/` — FilterToolbar, PageHeader, TabNav + subdirs: dashboard/ (6 widgets), import/ (BankImportWizard, MarketplaceImportWizard), settings/ (SourcesManager, OmsStoresManager)
- `app/composables/` — useAccounts, useAsyncAction, useCsvFileUpload, useCsvMapping, useDatev, useDatevSettings, useDocumentExtraction, useFilterVisibility, useFormatters, useImportWizardBase, useLinkingModal, useMarketplaceEnrichment, useMarketplaceParsing, useOms, useOmsProviders, usePaginatedFetch, usePaypal, usePublicSettings, useQueryTab, useReceiptTotals, useReceipts, useSources, useTransactions, useUrlFilters (OMS = pluggable Order Management System; Billbee is the configured provider)
- `app/types/` — `api.ts` (all API response/request types), `auth.d.ts` (session types)
- `app/middleware/auth.ts` — Client-side redirect to /login
- `server/routes/` — API proxy + Google OAuth callback
- `server/middleware/` — Strip X-User headers (00), auth + session + idle timeout + X-Proxy-Secret injection (auth)
- `server/plugins/validate-env.ts` — Fail-fast startup validation

## Key Patterns

- **API Proxy** — `server/routes/api/v1/[...path].ts` forwards `/api/v1/**` to FastAPI
- **Auth** — Google OAuth via nuxt-auth-utils. Server middleware injects `X-User-*` + `X-Proxy-Secret` headers.
- **Session** — Cookie-based, 120min idle timeout, throttled activity updates (60s)
- **State** — Pure composables (queries via `useFetch`, mutations via `$fetch`), no Pinia
- **Entrypoint** — `entrypoint.sh` maps env vars for production (SESSION_SECRET→NUXT_SESSION_PASSWORD, GOOGLE_*→NUXT_OAUTH_GOOGLE_*, ALLOWED_EMAILS/ALLOWED_EMAIL_DOMAINS→NUXT_ALLOWED_*, API_URL→NUXT_API_URL)
- **Login allowlist** — Auth Mode gate in `server/routes/auth/google.get.ts` via `server/utils/emailAllowlist.ts` (`isLoginAllowed`, `isAllowlistConfigured`). Config: `allowedEmails`/`allowedEmailDomains` runtimeConfig. Fail-closed: empty = deny (app still runs); `validate-env.ts` warns at startup when unset. Login route redirects `?error=forbidden` (not on list) vs `?error=login_not_configured` (no allowlist). `ALLOWED_EMAIL_DOMAINS=*` = explicit opt-in to allow any Google account.

## Dependencies

date-fns, zod, @vueuse/nuxt, vitest (test runner)

## Gotchas

- **`localhost` doesn't resolve on macOS** — always use `http://127.0.0.1:3002`, never `http://localhost:3002`
- **Google OAuth redirect URI must match exactly** — `http://127.0.0.1:3002/auth/google` in Google Cloud Console
