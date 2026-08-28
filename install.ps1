# 🧾 shop2tax – Installations-Script (Windows PowerShell)
#
# Verwendung:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\install.ps1
#
# Was passiert:
#   1. Prüft Docker + Docker Compose
#   2. Erstellt .env mit sicheren Secrets
#   3. Startet die Anwendung via Docker Compose
#   4. shop2tax ist danach unter http://127.0.0.1:3002 erreichbar

$ErrorActionPreference = "Stop"

# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

function Write-Info    { param($Message) Write-Host "ℹ  $Message" -ForegroundColor Blue }
function Write-Success { param($Message) Write-Host "✅ $Message" -ForegroundColor Green }
function Write-Warn    { param($Message) Write-Host "⚠️  $Message" -ForegroundColor Yellow }
function Write-Error-And-Exit {
    param($Message)
    Write-Host "❌ $Message" -ForegroundColor Red
    exit 1
}

# ─── Secret-Generierung (ohne openssl) ───────────────────────────────────────

function New-HexSecret {
    param([int]$Bytes = 16)
    $randomBytes = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes)
    return ($randomBytes | ForEach-Object { $_.ToString("x2") }) -join ""
}

# ─── Voraussetzungen prüfen ──────────────────────────────────────────────────

Write-Host ""
Write-Host "🧾 shop2tax – Installation" -ForegroundColor Blue
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Write-Host ""

# Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error-And-Exit @"
Docker ist nicht installiert.

  Installiere Docker Desktop:
    https://docs.docker.com/desktop/install/windows-install/

  Nach der Installation: Docker Desktop starten und dieses Script erneut ausführen.
"@
}

# Docker Daemon läuft?
$dockerInfo = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error-And-Exit @"
Docker läuft nicht.

  Bitte starte Docker Desktop und führe dieses Script erneut aus.
"@
}

# Docker Compose
$composeVersion = docker compose version --short 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error-And-Exit @"
Docker Compose ist nicht verfügbar.

  Docker Compose v2 wird als Docker-Plugin benötigt.
  Bei Docker Desktop ist es bereits enthalten.

  Prüfe: docker compose version
"@
}

# Mindestversion 2.20
$versionParts = $composeVersion.Split(".")
$major = [int]$versionParts[0]
$minor = [int]$versionParts[1]
if ($major -lt 2 -or ($major -eq 2 -and $minor -lt 20)) {
    Write-Error-And-Exit @"
Docker Compose $composeVersion ist zu alt (mindestens 2.20 benötigt).

  Bitte aktualisiere Docker Desktop auf die neueste Version.
"@
}

$dockerVersion = (docker --version) -replace "Docker version ", "" -replace ",.*", ""
Write-Success "Docker $dockerVersion + Compose $composeVersion gefunden"

# Pfade
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envExample = Join-Path $scriptDir ".env.example"
$envFile = Join-Path $scriptDir ".env"

# Port frei? (WEB_PORT aus vorhandener .env, sonst 3002)
$webPort = 3002
if ((Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^WEB_PORT=' -Quiet)) {
    $webPort = [int]((Select-String -Path $envFile -Pattern '^WEB_PORT=(\d+)' | Select-Object -Last 1).Matches[0].Groups[1].Value)
}
$portInUse = Get-NetTCPConnection -LocalPort $webPort -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Warn "Port $webPort ist bereits belegt."
    Write-Host ""
    Write-Host "  Ein anderer Dienst nutzt Port $webPort. Entweder:"
    Write-Host "    1. Den anderen Dienst beenden"
    Write-Host "    2. Oder shop2tax auf einem anderen Port starten: WEB_PORT=3003 in .env setzen"
    Write-Host ""
    Write-Error-And-Exit "Port $webPort ist nicht verfügbar."
}

# .env.example vorhanden?

if (-not (Test-Path $envExample)) {
    Write-Error-And-Exit @"
.env.example nicht gefunden.

  Bitte führe dieses Script im shop2tax-Verzeichnis aus:
    cd C:\pfad\zu\shop2tax
    .\install.ps1
"@
}

Write-Success "Alle Voraussetzungen erfüllt"
Write-Host ""

# ─── .env erstellen ──────────────────────────────────────────────────────────

if (Test-Path $envFile) {
    Write-Warn ".env existiert bereits — wird nicht überschrieben."
    Write-Info "Zum Zurücksetzen: Remove-Item .env; .\install.ps1"
} else {
    Write-Info "Erstelle .env mit sicheren Secrets..."

    $content = Get-Content $envExample -Raw

    # Secrets generieren
    $postgresPw    = New-HexSecret -Bytes 16
    $proxySecret   = New-HexSecret -Bytes 32
    $sessionSecret = New-HexSecret -Bytes 32

    # Platzhalter ersetzen
    $content = $content -replace "POSTGRES_PASSWORD=change-me-in-production", "POSTGRES_PASSWORD=$postgresPw"
    # NUXT_PROXY_SECRET und SESSION_SECRET auskommentieren + Wert setzen
    $content = $content -replace "(?m)^# NUXT_PROXY_SECRET=.*$", "NUXT_PROXY_SECRET=$proxySecret"
    $content = $content -replace "(?m)^# SESSION_SECRET=.*$", "SESSION_SECRET=$sessionSecret"

    # Ohne BOM schreiben (Docker liest UTF-8 ohne BOM)
    [System.IO.File]::WriteAllText($envFile, $content, [System.Text.UTF8Encoding]::new($false))

    Write-Success ".env erstellt mit sicheren Secrets"
}

Write-Host ""

# ─── Docker Compose starten ──────────────────────────────────────────────────

Write-Info "Starte shop2tax (erster Start kann einige Minuten dauern)..."
Write-Host ""

Push-Location $scriptDir
try {
    docker compose up --build -d
    if ($LASTEXITCODE -ne 0) {
        Write-Error-And-Exit "Docker Compose konnte nicht gestartet werden. Prüfe die Ausgabe oben."
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Write-Host ""
Write-Success "shop2tax wurde erfolgreich gestartet!"
Write-Host ""
Write-Host "  ▶  Öffne im Browser: " -NoNewline
Write-Host "http://127.0.0.1:$webPort" -ForegroundColor Blue
Write-Host ""
Write-Host "  Hinweis: Beim ersten Start werden Datenbank-Migrationen" -ForegroundColor Yellow
Write-Host "  und Stammdaten geladen. Das kann bis zu 30 Sekunden dauern."
Write-Host ""
Write-Host "  Nützliche Befehle:"
Write-Host "    docker compose logs -f     Logs anzeigen"
Write-Host "    docker compose down        Stoppen"
Write-Host "    docker compose up -d       Wieder starten"
Write-Host ""
