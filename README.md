<h1 align="center">shop2tax</h1>

<p align="center">
  <strong>Self-Hosted Buchhaltung für deutsche Kleinunternehmer.</strong><br>
  CSV-Dateien rein → SKR03-Kontierung → DATEV-Export raus. Fertig.
</p>

<p align="center">
  <a href="https://www.gnu.org/licenses/agpl-3.0"><img src="https://img.shields.io/badge/License-AGPL_v3-blue.svg" alt="License: AGPL v3"></a>
  <a href="https://github.com/shop2tax/shop2tax/actions/workflows/ci.yml"><img src="https://github.com/shop2tax/shop2tax/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <img src="https://img.shields.io/badge/Status-Early_Access-orange" alt="Status: Early Access">
  <img src="https://img.shields.io/badge/Made_with-Claude_Code-blueviolet" alt="Made with Claude Code">
</p>

&nbsp;

## 🎯 Das Problem

Du verkaufst nebenberuflich auf Amazon, Etsy oder Shopify und nutzt eventuell sogar noch Billbee? Dein Steuerberater will DATEV-Dateien und du zahlst 15–30 €/Monat für Buchhaltungssoftware, von der du nur maximal 50 % der Features nutzt? Genauso ging es mir seit 2020 und ich wollte schon immer gerne diese laufenden Abo-Kosten reduzieren.

Mit **shop2tax** versuche ich genau diesen Kosten entgegenzuwirken. Dabei ist es egal, ob du Kleinunternehmer nach §19 UStG bist oder umsatzsteuerpflichtig — shop2tax funktioniert für beides. Wichtig ist, dass du einen Steuerberater hast und mit diesem die Vorgänge besprechen kannst.

**Status:** shop2tax deckt aktuell den Weg von CSV-Import bis DATEV-Export ab. Rechnungsstellung und EÜR-Erstellung sind geplant. Umsatzsteuer-Voranmeldung ist nicht vorgesehen — dafür gibt es den Steuerberater.

&nbsp;

## ⚡ So funktioniert's

```
  CSV-Import          Kontierung           Export
┌─────────────┐     ┌───────────────┐     ┌──────────┐
│  Amazon     │     │               │     │          │
│  Etsy       │────▶│  SKR03-Konten │────▶│  DATEV   │
│  Shopify    │     │  ~40 kuratiert│     │  EXTF    │
│  Stripe     │     │               │     │          │
│  Bank-CSVs  │     └───────────────┘     └──────────┘
└─────────────┘           ▲                     │
                          │                     ▼
                 📎 Billbee Belege      📧 Steuerberater
```

&nbsp;

## 🚀 Quick Start

```bash
git clone https://github.com/shop2tax/shop2tax.git
cd shop2tax
./install.sh
```

> **Windows**: In PowerShell zuerst `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` ausführen, dann `.\install.ps1`.

Öffne **http://127.0.0.1:3002** im Browser.

> **Local Mode aktiv**: Ohne Google OAuth-Konfiguration läuft die App sofort — kein Login nötig. Die Oberfläche ist standardmäßig nur auf deinem Rechner erreichbar (`127.0.0.1`). Alles Weitere steht in der [Installationsanleitung](docs/installation.md).

&nbsp;

## ✨ Aktuelle Features

### Import & Datenquellen
- **Universeller Bank-CSV-Parser** — Automatische Erkennung von Trennzeichen, Encoding, Datums- und Betragsformat. Spalten-Mapping pro Quelle konfigurierbar, funktioniert mit jeder Bank
- **Marktplatz-Import** — Amazon, Etsy, Shopify, Stripe mit Billbee-Anreicherung
- **PayPal-Sync** — API-basierter Transaktionsimport mit automatischer Gebührentrennung
- **Billbee-Integration** — Auftragsabgleich, automatische Belegerstellung inkl. PDF-Download
- **Duplikaterkennung** — Hash-basiert (Banken) + Zeitfenster-basiert (Marktplätze)

### Belege & OCR
- **Optional konfigurierbare Belegextraktion mit 3 KI-Anbietern** — Google Gemini, OpenAI und Anthropic Claude. Modell frei wählbar, Kosten pro Beleg transparent im Dashboard
- **ZUGFeRD / XRechnung** — Automatische XML-Extraktion aus PDF/A-3, kostenlos und ohne KI
- **Belegverwaltung** — GoBD-konforme WORM-Speicherung in Google Cloud Storage (oder lokal für den Einstieg), SHA-256-Integritätsprüfung
- **Intelligente Kontierungsvorschläge** — Lernt aus finalisierten Belegen, welches SKR03-Konto zu welchem Lieferanten passt

### Buchhaltung & Export
- **SKR03-Kontierung** — ~40 kuratierte E-Commerce-Konten, belegbasierte Zuordnung auf Positionsebene
- **DATEV-Export** — Buchungsstapel (EXTF) als ZIP mit Belegdokumenten, validiert vor Download
- **Zahlungsabgleich** — Automatische Vorschläge: Betrag, Empfänger, Datum-Nähe mit Konfidenz-Score
- **Interne Umbuchungen** — Geldbewegungen zwischen Konten verknüpfen (z. B. PayPal → Bank)

### Betrieb & Sicherheit
- **Local Mode** — `./install.sh` und los, kein Login, kein Cloud-Account nötig
- **Google OAuth** — Optional für Mehrbenutzerbetrieb, mit Login-Allowlist (`ALLOWED_EMAILS` / `ALLOWED_EMAIL_DOMAINS`) zum Einschränken erlaubter Konten
- **GoBD-Compliance** — WORM-Storage, Audit-Log, Finalisierung mit Sperrung
- **Dashboard** — Gewinn/Verlust, Kleinunternehmer-Schwelle, Buchungsfortschritt, KI-Kosten
- **Sicherheit** — Rate Limiting, API nur über den Nuxt-Proxy erreichbar, keine Secrets im Image

> **Austauschbar by Design:** shop2tax ist so gebaut, dass Integrationen jederzeit ersetzt werden können. Billbee lässt sich gegen eine andere Warenwirtschaft tauschen, Google Cloud Storage gegen jeden Storage-Anbieter mit WORM-Support (z. B. AWS S3 Object Lock). Keine Anbieterabhängigkeit.

&nbsp;

## 🏗️ Architektur

```
┌─────────────┐     ┌────────────────────────┐     ┌─────────────┐     ┌──────────────┐
│   Browser   │────▶│  Nuxt 4 (SSR + Auth)   │────▶│   FastAPI   │────▶│ PostgreSQL 16│
└─────────────┘     └────────────────────────┘     └─────────────┘     └──────────────┘
                           pnpm                      Python 3.12            SQLAlchemy
                        Nuxt UI v4                       UV                   Alembic
```

**Alles läuft in Docker** — kein lokales Python/Node erforderlich. Für den Betrieb mit eigener Domain und HTTPS liegt eine Caddy-Konfiguration bei.

&nbsp;

## 📚 Dokumentation

| Dokument | Beschreibung |
|----------|--------------|
| [Installation](docs/installation.md) | Systemanforderungen, Anwender- vs. Entwickler-Setup, Update, Produktion |
| [DATEV-Export](docs/datev-export.md) | Buchungsstapel-Format, BU-Schlüssel, Gegenkonto |
| [Etsy-Import](docs/etsy-import.md) | Etsy Payment Account Statement, Transaktionstypen, §13b |
| [GCS-Setup](docs/gcs-setup.md) | Google Cloud Storage für GoBD-konforme Belegablage |
| [Google OAuth](docs/google-oauth-setup.md) | Mehrbenutzerbetrieb mit Google-Login |

&nbsp;

## 🤖 Entwickelt mit Claude Code

Nach 6 Jahren sevDesk, lexoffice & Co. lag die Lösung nahe: selbst bauen. Dieses Projekt entsteht vollständig im Dialog mit KI — Architektur, Code, Tests und Dokumentation. [Claude Code](https://docs.anthropic.com/en/docs/claude-code) ist dabei nicht nur Werkzeug, sondern Entwicklungspartner. Das Repository enthält gepflegte `CLAUDE.md`-Kontextdateien für das Projekt, das Backend (`apps/api`) und das Frontend (`apps/web`) mit Architektur-Patterns und Konventionen — so kann Claude Code sofort produktiv mitarbeiten, ohne erst die Codebasis verstehen zu müssen.

&nbsp;

## 📍 Roadmap

### Erledigt
- [x] Universeller Bank-CSV-Import mit Auto-Erkennung
- [x] Marktplatz-CSV-Import (Amazon, Etsy, Shopify, Stripe)
- [x] Dedizierter Etsy-Parser — 13 Transaktionstypen, §13b Reverse Charge, Verrechnungskonto, Sammelbelege
- [x] Dedizierter Shopify-Parser — Payment Transactions mit automatischer Gebührentrennung
- [x] Dedizierter Amazon-Parser — Settlement Reports mit Marketplace-spezifischer Gebührenstruktur (FBA, Referral Fees, Advertising)
- [x] Reverse Charge (§13b UStG) — Automatische Erkennung von EU-Auslands-Gebühren (z. B. Etsy Ireland), korrekte Steuerschuldumkehr auf Belegebene, USt-VA-konforme Kontierung, Compliance-Endpoint zur Verifizierung
- [x] Sammelbelege (M:N) — Mehrere Transaktionen mit einem Beleg verknüpfen (Bulk Linking)
- [x] Belegverwaltung mit GoBD-Compliance (WORM, Audit-Log)
- [x] OCR-Belegextraktion (Gemini, OpenAI, Claude) + ZUGFeRD/XRechnung
- [x] SKR03-Kontierung mit lernenden Vorschlägen + Kontenverwaltung in der UI
- [x] DATEV-Export (Buchungsstapel + Belegdokumente als ZIP)
- [x] Billbee-Integration (Aufträge, Belege, PDF-Download)
- [x] PayPal-API-Sync (Transaktionen, Gebührentrennung)
- [x] PayPal-Gebühren-Kontierung — Gebühren als separate Transactions importiert, SKR03 4970 via Pattern-Learning, monatlicher Kontoauszug als Sammelbeleg
- [x] Automatische Belegzuordnung (Billbee) — Transaktionen und Belege per Order-ID verknüpfen, bidirektional nach CSV-Import und Billbee-Sync
- [x] Austauschbare Warenwirtschafts-Anbindung — Provider-Abstraktion, Billbee als erste Implementierung, weitere Warenwirtschaftssysteme andockbar
- [x] Dashboard (Gewinn/Verlust, Kleinunternehmer-Schwelle, KI-Kosten)
- [x] Dark Mode
- [x] Einrichtung ohne Konfiguration (install.sh / install.ps1)

### Geplant

**Automatische Belegzuordnung (PayPal, Banken)**
- [ ] Transaktionen und Belege automatisch verknüpfen per Betrag, Datum, Empfänger und weiteren Faktoren

**finAPI-Anbindung**
- [ ] Automatischer Banktransaktions-Import per PSD2-Schnittstelle, kein manueller CSV-Download mehr nötig

**Weitere geplante Features:**
- [ ] Rechnungsstellung
- [ ] EÜR-Erstellung
- [ ] Öffentliche Dokumentation

> Umsatzsteuer-Voranmeldung ist vorerst nicht geplant — dafür gibt's den Steuerberater.

&nbsp;

## 🤝 Mitmachen

Das Projekt ist in aktiver Entwicklung. Feedback, Feature-Wünsche und Beiträge sind willkommen — einfach ein [Issue](https://github.com/shop2tax/shop2tax/issues) erstellen. Für Pull Requests siehe [CONTRIBUTING.md](CONTRIBUTING.md).

&nbsp;

## 📄 Lizenz

[GNU Affero General Public License v3.0](LICENSE) — Free as in freedom.
