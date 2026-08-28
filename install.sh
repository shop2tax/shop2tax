#!/usr/bin/env bash
# 🧾 shop2tax – Installations-Script (Mac/Linux)
#
# Verwendung:
#   chmod +x install.sh && ./install.sh
#
# Was passiert:
#   1. Prüft Docker + Docker Compose
#   2. Erstellt .env mit sicheren Secrets
#   3. Startet die Anwendung via Docker Compose
#   4. shop2tax ist danach unter http://127.0.0.1:3002 erreichbar

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Farben ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()    { echo -e "${BLUE}ℹ${NC}  $1"; }
success() { echo -e "${GREEN}✅${NC} $1"; }
warn()    { echo -e "${YELLOW}⚠️${NC}  $1"; }
error()   { echo -e "${RED}❌${NC} $1"; exit 1; }

# ─── Voraussetzungen prüfen ──────────────────────────────────────────────────

echo ""
echo -e "${BLUE}🧾 shop2tax – Installation${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Docker
if ! command -v docker &>/dev/null; then
    error "Docker ist nicht installiert.

  Installiere Docker Desktop:
    Mac:     https://docs.docker.com/desktop/install/mac-install/
    Linux:   https://docs.docker.com/engine/install/

  Nach der Installation: Docker Desktop starten und dieses Script erneut ausführen."
fi

# Docker Daemon läuft?
if ! docker info &>/dev/null; then
    error "Docker läuft nicht.

  Bitte starte Docker Desktop und führe dieses Script erneut aus."
fi

# Docker Compose (v2, als Plugin)
if ! docker compose version &>/dev/null; then
    error "Docker Compose ist nicht verfügbar.

  Docker Compose v2 wird als Docker-Plugin benötigt.
  Bei Docker Desktop ist es bereits enthalten.

  Prüfe: docker compose version"
fi

# Docker Compose Mindestversion 2.20 (für profiles, healthcheck improvements)
COMPOSE_VERSION=$(docker compose version --short 2>/dev/null || echo "0.0.0")
COMPOSE_MAJOR=$(echo "$COMPOSE_VERSION" | cut -d. -f1)
COMPOSE_MINOR=$(echo "$COMPOSE_VERSION" | cut -d. -f2)
if [ "$COMPOSE_MAJOR" -lt 2 ] || { [ "$COMPOSE_MAJOR" -eq 2 ] && [ "$COMPOSE_MINOR" -lt 20 ]; }; then
    error "Docker Compose $COMPOSE_VERSION ist zu alt (mindestens 2.20 benötigt).

  Bitte aktualisiere Docker Desktop auf die neueste Version."
fi

success "Docker $(docker --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+') + Compose $COMPOSE_VERSION gefunden"

# Port frei? (WEB_PORT aus vorhandener .env, sonst 3002)
WEB_PORT=3002
if [ -f "$SCRIPT_DIR/.env" ] && grep -qE '^WEB_PORT=' "$SCRIPT_DIR/.env"; then
    WEB_PORT=$(grep -E '^WEB_PORT=' "$SCRIPT_DIR/.env" | tail -1 | cut -d= -f2)
fi
if command -v lsof &>/dev/null && lsof -i :"$WEB_PORT" &>/dev/null; then
    warn "Port $WEB_PORT ist bereits belegt."
    echo ""
    echo "  Ein anderer Dienst nutzt Port $WEB_PORT. Entweder:"
    echo "    1. Den anderen Dienst beenden"
    echo "    2. Oder shop2tax auf einem anderen Port starten: WEB_PORT=3003 in .env setzen"
    echo ""
    error "Port $WEB_PORT ist nicht verfügbar."
fi

# openssl (für Secret-Generierung)
if ! command -v openssl &>/dev/null; then
    error "openssl ist nicht installiert.

  Installiere openssl:
    Mac:   brew install openssl
    Linux: sudo apt install openssl (oder yum install openssl)"
fi

# .env.example vorhanden?
if [ ! -f "$SCRIPT_DIR/.env.example" ]; then
    error ".env.example nicht gefunden.

  Bitte führe dieses Script im shop2tax-Verzeichnis aus:
    cd /pfad/zu/shop2tax
    ./install.sh"
fi

success "Alle Voraussetzungen erfüllt"
echo ""

# ─── .env erstellen ──────────────────────────────────────────────────────────

if [ -f "$SCRIPT_DIR/.env" ]; then
    warn ".env existiert bereits — wird nicht überschrieben."
    info "Zum Zurücksetzen: rm .env && ./install.sh"
else
    info "Erstelle .env mit sicheren Secrets..."

    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"

    # Secrets generieren
    POSTGRES_PW=$(openssl rand -hex 16)
    PROXY_SECRET=$(openssl rand -hex 32)
    SESSION_SECRET=$(openssl rand -hex 32)

    # Platzhalter in .env ersetzen
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS sed braucht -i ''
        sed -i '' "s|POSTGRES_PASSWORD=change-me-in-production|POSTGRES_PASSWORD=$POSTGRES_PW|" "$SCRIPT_DIR/.env"
        # NUXT_PROXY_SECRET und SESSION_SECRET auskommentieren + Wert setzen
        sed -i '' "s|^# NUXT_PROXY_SECRET=.*|NUXT_PROXY_SECRET=$PROXY_SECRET|" "$SCRIPT_DIR/.env"
        sed -i '' "s|^# SESSION_SECRET=.*|SESSION_SECRET=$SESSION_SECRET|" "$SCRIPT_DIR/.env"
    else
        # Linux sed
        sed -i "s|POSTGRES_PASSWORD=change-me-in-production|POSTGRES_PASSWORD=$POSTGRES_PW|" "$SCRIPT_DIR/.env"
        sed -i "s|^# NUXT_PROXY_SECRET=.*|NUXT_PROXY_SECRET=$PROXY_SECRET|" "$SCRIPT_DIR/.env"
        sed -i "s|^# SESSION_SECRET=.*|SESSION_SECRET=$SESSION_SECRET|" "$SCRIPT_DIR/.env"
    fi

    success ".env erstellt mit sicheren Secrets"
fi

echo ""

# ─── Docker Compose starten ──────────────────────────────────────────────────

info "Starte shop2tax (erster Start kann einige Minuten dauern)..."
echo ""

cd "$SCRIPT_DIR"
docker compose up --build -d

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
success "shop2tax wurde erfolgreich gestartet!"
echo ""
echo -e "  ${GREEN}▶${NC}  Öffne im Browser: ${BLUE}http://127.0.0.1:$WEB_PORT${NC}"
echo ""
echo -e "  ${YELLOW}Hinweis:${NC} Beim ersten Start werden Datenbank-Migrationen"
echo "  und Stammdaten geladen. Das kann bis zu 30 Sekunden dauern."
echo ""
echo "  Nützliche Befehle:"
echo "    docker compose logs -f     Logs anzeigen"
echo "    docker compose down        Stoppen"
echo "    docker compose up -d       Wieder starten"
echo ""
