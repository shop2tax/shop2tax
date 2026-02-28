<h1 align="center">shop2tax</h1>

<p align="center">
  <strong>Self-Hosted Buchhaltung für deutsche Kleinunternehmer.</strong><br>
  CSV-Dateien rein → SKR03-Kontierung → DATEV-Export raus. Fertig.
</p>

<p align="center">
  <a href="https://www.gnu.org/licenses/agpl-3.0"><img src="https://img.shields.io/badge/License-AGPL_v3-blue.svg" alt="License: AGPL v3"></a>
  <img src="https://img.shields.io/badge/Status-Early_Access-orange" alt="Status: Early Access">
  <img src="https://img.shields.io/badge/Made_with-Claude_Code-blueviolet" alt="Made with Claude Code">
</p>

&nbsp;

## 🎯 Das Problem

Du verkaufst nebenberuflich auf Amazon, Etsy oder Shopify und nutzt eventuell sogar noch Billbee? Dein Steuerberater will DATEV-Dateien und du zahlst 15–30 €/Monat für Buchhaltungssoftware, von der du nur maximal 50 % der Features nutzt? Genauso ging es mir seit 2020 und ich wollte schon immer gerne diese laufenden Abo-Kosten reduzieren.

Mit **shop2tax** versuche ich genau diesen Kosten entgegen zu wirken. Dabei ist es egal, ob du Kleinunternehmer nach §19 UStG bist oder umsatzsteuerpflichtig — shop2tax funktioniert für beides. Wichtig ist das du einen Steuerberater hast und mit diesen die Vorgänge besprechen kannst. 

&nbsp;

## ⚡ So funktioniert's

```
  CSV-Import          Kontierung           Export
┌─────────────┐     ┌───────────────┐     ┌──────────┐
│  Amazon     │     │               │     │          │
│  Etsy       │────▶│  SKR03-Konten │────▶│  DATEV   │
│  Shopify    │     │  ~40 kuratiert│     │  EXTF    │
│  Stripe     │     │               │     │          │
│  Bank-CSV's │     └───────────────┘     └──────────┘
└─────────────┘           ▲                     │
                          │                     ▼
                 📎 Billbee Belege      📧 Steuerberater
```

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
- **Belegverwaltung** — GoBD-konforme WORM-Speicherung in Google Cloud Storage, SHA-256-Integritätsprüfung
- **Intelligente Kontierungsvorschläge** — Lernt aus finalisierten Belegen, welches SKR03-Konto zu welchem Lieferanten passt

### Buchhaltung & Export
- **SKR03-Kontierung** — ~40 kuratierte E-Commerce-Konten, belegbasierte Zuordnung auf Positionsebene
- **DATEV-Export** — Buchungsstapel (EXTF) als ZIP mit Belegdokumenten, validiert vor Download
- **Zahlungsabgleich** — Automatische Vorschläge: Betrag, Empfänger, Datum-Nähe mit Konfidenz-Score
- **Interne Umbuchungen** — Geldbewegungen zwischen Konten verknüpfen (z. B. PayPal → Bank)

### Betrieb & Sicherheit
- **Local Mode** — `docker compose up` und los, kein Login, kein Cloud-Account nötig
- **Google OAuth** — Optional für Mehrbenutzerbetrieb
- **GoBD-Compliance** — WORM-Storage, Audit-Log, Finalisierung mit Sperrung, Jahresabschluss
- **Dashboard** — Gewinn/Verlust, Kleinunternehmer-Schwelle, Buchungsfortschritt, KI-Kosten

> **Austauschbar by Design:** shop2tax ist so gebaut, dass Integrationen jederzeit ersetzt werden können. Billbee lässt sich gegen eine andere WaWi tauschen, Google Cloud Storage gegen jeden Storage-Anbieter mit WORM-Support (z. B. AWS S3 Object Lock). Kein Vendor Lock-in.

&nbsp;

## 🏗️ Tech Stack

| Layer | Technologie |
|-------|-------------|
| Frontend | Nuxt 4, Nuxt UI v4, pnpm |
| Backend | FastAPI, Python 3.12, UV |
| Datenbank | PostgreSQL 16, SQLAlchemy 2, Alembic |
| Infrastruktur | Docker Compose, Caddy (Prod) |

&nbsp;

## 📍 Roadmap

### Erledigt
- [x] Universeller Bank-CSV-Import mit Auto-Erkennung
- [x] Marktplatz-CSV-Import (Amazon, Etsy, Shopify, Stripe)
- [x] Belegverwaltung mit GoBD-Compliance (WORM, Audit-Log)
- [x] OCR-Belegextraktion (Gemini, OpenAI, Claude) + ZUGFeRD/XRechnung
- [x] SKR03-Kontierung mit lernenden Vorschlägen
- [x] DATEV-Export (Buchungsstapel + Belegdokumente als ZIP)
- [x] Billbee-Integration (Aufträge, Belege, PDF-Download)
- [x] PayPal-API-Sync (Transaktionen, Gebührentrennung)
- [x] Dashboard (Gewinn/Verlust, Kleinunternehmer-Schwelle, KI-Kosten)

### Geplant

**Dedizierte Marktplatz-Parser** — Aktuell nutzen alle Marktplatz-CSVs den generischen Parser mit manuellem Spalten-Mapping. Geplant sind dedizierte Parser, die marktplatzspezifische Besonderheiten automatisch erkennen und korrekt verbuchen:

- [ ] **Etsy-Parser** — Automatische Erkennung aller 12+ Transaktionstypen (Sales, Fees, Refunds, Ads, Payouts), korrekte §13b Reverse-Charge-Behandlung je nach Steuerstatus, Verrechnungskonto (1201) mit Saldoabstimmung gegen Etsy-Dashboard, Geldtransit-Buchungen für Auszahlungen
- [ ] **Shopify-Parser** — Analoges Konzept für Shopify Payments mit Gebührentrennung und Auszahlungsverfolgung
- [ ] **Amazon-Parser** — Settlement Reports mit Marketplace-spezifischer Gebührenstruktur (FBA, Referral Fees, Advertising)

**PayPal-Gebühren-Kontierung**
- [ ] PayPal-Transaktionsgebühren werden aktuell importiert, aber noch nicht automatisch als separate Betriebsausgaben auf eigene SKR03-Konten verbucht.

**finAPI-Anbindung**
- [ ] Automatischer Banktransaktions-Import per PSD2-Schnittstelle, kein manueller CSV-Download mehr nötig

**Weitere geplante Features:**
- [ ] Rechnungsstellung
- [ ] EÜR-Erstellung
- [ ] Öffentliche Dokumentation

> Umsatzsteuer-Voranmeldung ist vorerst nicht geplant — dafür gibt's den Steuerberater.

&nbsp;

## 🤝 Mitmachen

Das Projekt ist in aktiver Entwicklung. Feedback, Feature-Wünsche und Beiträge sind willkommen — einfach ein [Issue](https://github.com/shop2tax/shop2tax/issues) erstellen.

&nbsp;

## 📄 Lizenz

[GNU Affero General Public License v3.0](LICENSE) — Free as in freedom.
