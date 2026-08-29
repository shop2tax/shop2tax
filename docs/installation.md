# Installation

Diese Anleitung beschreibt die Installation von shop2tax für **Anwender** (Docker-only) und **Entwickler** (lokale Toolchain).

## Systemanforderungen

| Anforderung | Minimum | Empfohlen |
|-------------|---------|-----------|
| Docker Desktop | 4.20+ | Aktuell |
| Docker Engine | 24.0+ | Aktuell |
| Docker Compose | 2.20+ | Aktuell |
| RAM | 4 GB | 8 GB |
| Speicherplatz | 2 GB | 5 GB |

> 💡 **Docker Desktop** enthält Docker Engine und Compose. Unter Windows/macOS ist Docker Desktop die empfohlene Installation.

## Für Anwender

> **Windows**: Die Befehle in PowerShell ausführen. Vorher einmalig `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` eingeben (gilt nur für die aktuelle Sitzung), sonst verweigert Windows das Skript.

### Option A: Git Clone (empfohlen)

```bash
git clone https://github.com/shop2tax/shop2tax.git
cd shop2tax
./install.sh    # Mac/Linux
# oder
.\install.ps1   # Windows (PowerShell)
```

### Option B: ZIP-Download

1. Lade das Projekt als ZIP herunter: [shop2tax-main.zip](https://github.com/shop2tax/shop2tax/archive/refs/heads/main.zip) (auf GitHub: „Code → Download ZIP")
2. Entpacke das Archiv
3. Öffne ein Terminal im entpackten Ordner
4. Führe das Install-Script aus:
   ```bash
   ./install.sh    # Mac/Linux
   .\install.ps1   # Windows (PowerShell)
   ```

### Was macht das Install-Script?

1. Prüft ob Docker läuft und Port 3002 frei ist
2. Kopiert `.env.example` → `.env` (falls nicht vorhanden)
3. Generiert sichere Zufallswerte für:
   - `POSTGRES_PASSWORD` — Datenbank-Passwort
   - `NUXT_PROXY_SECRET` — Interne API-Absicherung
   - `SESSION_SECRET` — Session-Verschlüsselung
4. Baut die Production-Images und startet alle Container mit `docker compose up --build`

### Nach der Installation

Öffne **http://127.0.0.1:3002** im Browser.

> ⚠️ **Wichtig**: Verwende `127.0.0.1`, nicht `localhost`. Unter macOS gibt es DNS-Probleme mit `localhost`.

## Erste Schritte

Nach dem ersten Start siehst du ein leeres Dashboard. So legst du los:

### 1. CSV importieren

1. Klicke auf **Import** in der Navigation
2. Wähle den Dateityp (Amazon, Etsy, Bank-CSV, etc.)
3. Lade deine CSV-Datei hoch
4. Prüfe die erkannten Transaktionen
5. Klicke **Importieren**

### 2. Transaktionen kontieren

1. Öffne eine importierte Transaktion
2. Weise SKR03-Konten zu (z.B. 8400 Erlöse 19%)
3. Verknüpfe optional einen Beleg
4. Speichere die Kontierung

### 3. DATEV-Export

1. Gehe zu **Einstellungen → DATEV**
2. Trage Beraternummer und Mandantennummer ein
3. Wähle den Exportzeitraum
4. Lade die CSV-Datei herunter
5. Sende sie an deinen Steuerberater

## Für Entwickler

Entwickler arbeiten mit der lokalen Toolchain für schnellere Iteration.

### Voraussetzungen

| Tool | Installation |
|------|-------------|
| [Docker Desktop](https://www.docker.com/products/docker-desktop) | Docker + Compose |
| [uv](https://docs.astral.sh/uv/) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [pnpm](https://pnpm.io/) | `npm install -g pnpm` |
| [pre-commit](https://pre-commit.com/) | `uv tool install pre-commit` |
| [mise](https://mise.jdx.dev/) (optional) | `mise install` — installiert Node, pnpm und uv in den Versionen aus `mise.toml` |

### Setup

```bash
git clone https://github.com/shop2tax/shop2tax.git
cd shop2tax

# Umgebungsvariablen einrichten
cp .env.example .env
# → Editiere .env und setze die REQUIRED-Variablen (siehe Tabelle unten)

# Voraussetzungen prüfen
make doctor

# Pre-Commit Hooks installieren
make setup

# Entwicklungsumgebung starten
make dev
```

### Wichtige Make-Befehle

| Befehl | Beschreibung |
|--------|--------------|
| `make dev` | Startet DB + API + Web mit Hot-Reload |
| `make dev-build` | Rebuild + Start aller Container |
| `make down` | Stoppt alle Container |
| `make logs` | Zeigt Container-Logs |
| `make check` | Lint + Typecheck + Build + Tests |
| `make lint-fix` | Automatische Code-Korrektur |
| `make test` | Pytest im Docker |

### Datenbank-Befehle

| Befehl | Beschreibung |
|--------|--------------|
| `make migrate` | Führt Alembic-Migrationen aus |
| `make migrate-new MSG="..."` | Erstellt neue Migration |
| `make db-shell` | PostgreSQL REPL |
| `make db-backup` | Backup nach `backups/` |
| `make db-reset` | Löscht alle Daten (destruktiv!) |

### Entwickler-Tools (dotenvx, optional)

Das Makefile lädt die `.env` über einen [dotenvx](https://dotenvx.com/)-Wrapper. Liegt eine `.env.keys` im Projektordner, wird eine verschlüsselte `.env` (plus optionale `.env.local`) zur Laufzeit entschlüsselt; fehlt sie, läuft alles mit einer normalen, unverschlüsselten `.env`. Es werden keine `.env`-Dateien im Repository eingecheckt.

> **Für Anwender und Contributors**: Du brauchst dotenvx nicht. Das Install-Script erstellt eine unverschlüsselte `.env`-Datei.

## Umgebungsvariablen

### Pflicht (REQUIRED)

Diese Variablen müssen gesetzt sein, sonst startet die App nicht:

| Variable | Beschreibung | Generiert von |
|----------|--------------|---------------|
| `POSTGRES_PASSWORD` | Datenbank-Passwort | install.sh |
| `NUXT_PROXY_SECRET` | Shared Secret zwischen Nuxt und API | install.sh |
| `SESSION_SECRET` | Session-Verschlüsselung (min. 32 Zeichen) | install.sh |

### Optional

Diese Variablen aktivieren zusätzliche Features:

| Variable | Feature | Standard |
|----------|---------|----------|
| `GOOGLE_CLIENT_ID` | Google OAuth Login | — (Local Mode) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth Login | — |
| `ALLOWED_EMAILS` | Login-Allowlist: erlaubte E-Mail-Adressen (kommagetrennt) | — (im Auth Mode Pflicht) |
| `ALLOWED_EMAIL_DOMAINS` | Login-Allowlist: erlaubte Domains (kommagetrennt; `*` = alle Konten) | — (im Auth Mode Pflicht) |
| `STORAGE_BACKEND` | Belegspeicher (`local` oder `gcs`) | `local` |
| `GCS_BUCKET_NAME` | GCS-Bucket für Belege | — |
| `BILLBEE_API_KEY` | Billbee-Integration | — |
| `PAYPAL_CLIENT_ID` | PayPal-Sync | — |
| `SENTRY_DSN` | Fehler-Tracking | — |

## Auth-Modi

shop2tax erkennt automatisch, welcher Modus aktiv ist:

| Modus | Bedingung | Verhalten |
|-------|-----------|-----------|
| **Local Mode** | `GOOGLE_CLIENT_ID` nicht gesetzt | Kein Login, alle Daten geteilt, System-User für Audit |
| **Auth Mode** | `GOOGLE_CLIENT_ID` gesetzt | Google OAuth erforderlich, Session-Management |

Für Mehrbenutzerbetrieb mit Login siehe [Google OAuth Setup](google-oauth-setup.md).

> ⚠️ **Auth Mode erfordert eine Login-Allowlist (secure by default).** Der Google-Login akzeptiert sonst jede Google-Adresse. Setze `ALLOWED_EMAILS` und/oder `ALLOWED_EMAIL_DOMAINS` — **ohne Allowlist wird im Auth Mode jeder Login abgewiesen** (die App läuft, aber niemand kommt rein; Warnung im Log). Um bewusst jedes Konto zuzulassen: `ALLOWED_EMAIL_DOMAINS=*`. Details: [Login-Allowlist](google-oauth-setup.md#schritt-4b-zugriff-einschränken-login-allowlist).

## Backup & Datensicherheit

### Wo liegen die Daten?

| Daten | Speicherort |
|-------|-------------|
| PostgreSQL | Docker Volume `shop2tax_postgres_data` |
| Lokale Belege | Docker Volume `shop2tax_receipt_storage` |
| GCS-Belege | Google Cloud Storage (unveränderbar) |

### Backup erstellen

```bash
# Datenbank-Backup
make db-backup
# → Erstellt backups/shop2tax_YYYY-MM-DD_HH-MM-SS.dump

# Lokale Belege sichern (falls STORAGE_BACKEND=local)
docker cp shop2tax-api-1:/data/receipts ./receipts-backup/
```

### Backup wiederherstellen

```bash
make db-restore FILE=backups/shop2tax_2026-01-15_14-30-00.dump
```

## Update

### Mit Git

```bash
git pull
docker compose build
docker compose up -d
```

### Mit ZIP-Download

1. Sichere deine `.env`-Datei
2. Lade die neue Version herunter
3. Entpacke und überschreibe die alten Dateien
4. Kopiere deine `.env`-Datei zurück
5. Starte neu:
   ```bash
   docker compose build
   docker compose up -d
   ```

## Produktion

Für den produktiven Einsatz:

```bash
docker compose -f docker-compose.prod.yml up -d
```

### Unterschiede zum Standard-Stack

| Aspekt | Standard (`install.sh`) | Produktion (`docker-compose.prod.yml`) |
|--------|-------------------------|----------------------------------------|
| SSL/TLS | Kein HTTPS | Caddy mit Auto-SSL |
| Port | 3002, nur auf 127.0.0.1 | 80/443 (Caddy) |
| API-Zugriff | Nur via Nuxt-Proxy | Nur via Nuxt-Proxy |
| Login | Optional (Local Mode möglich) | Google OAuth Pflicht |
| Belegspeicher | Lokal oder GCS | GCS (WORM) empfohlen |

### Domain konfigurieren

1. Setze `DOMAIN` in `.env`:
   ```
   DOMAIN=buchhaltung.deine-domain.de
   ```
2. Konfiguriere DNS (A-Record auf deinen Server)
3. Caddy holt automatisch ein Let's Encrypt-Zertifikat

### Google OAuth für Produktion

Redirect-URI in der Google Cloud Console aktualisieren:
```
https://buchhaltung.deine-domain.de/auth/google
```

## Fehlerbehebung

### "localhost" funktioniert nicht

Verwende `127.0.0.1` statt `localhost`. macOS hat bekannte DNS-Probleme mit localhost.

### Port 3002 belegt

```bash
# Prüfen, was den Port belegt
lsof -i :3002

# Anderen Port verwenden (in .env)
WEB_PORT=3003
```

### Container starten nicht

```bash
# Logs prüfen
docker compose logs

# Neu bauen
docker compose down
docker compose build --no-cache
docker compose up
```

### Datenbank-Fehler nach Update

```bash
# Migrationen ausführen
make migrate
```

