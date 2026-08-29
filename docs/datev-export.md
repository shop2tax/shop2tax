# DATEV-Export

shop2tax exportiert Buchungsstapel im DATEV EXTF-Format als CSV-Datei für den Import durch deinen Steuerberater.

## Dateistruktur

Die exportierte CSV besteht aus drei Abschnitten:

1. **Header-Zeile 1** — EXTF-Format-Metadaten (Version, Kategorie, Zeitstempel)
2. **Header-Zeile 2** — Leer (reserviert)
3. **Datenzeilen** — Eine Zeile pro Buchungszeile

## Header-Block

```
"EXTF";700;21;"Buchungsstapel";12;<timestamp>;;
"SV";"";"";;
<beraternummer>;<mandantennummer>;
<wj_beginn>;<sachkontenlaenge>;
<export_from>;<export_to>;
"";"";"";"";
```

| Feld | Beschreibung | Beispiel |
|------|--------------|----------|
| Beraternummer | Steuerberater-Nummer (7 Stellen) | `1234567` |
| Mandantennummer | Mandanten-Nummer (5 Stellen) | `12345` |
| WJ-Beginn | Beginn des Wirtschaftsjahres | `20260101` |
| Sachkontenlänge | Länge der Kontonummern | `4` |
| Export-Zeitraum | Datumsbereich (von/bis) | `20260101` / `20261231` |

## Spaltenzuordnung

| Spalte | DATEV-Name | Beschreibung | Beispiel |
|--------|-----------|--------------|----------|
| A | Umsatz | Bruttobetrag (immer positiv) | `119.00` |
| B | Soll/Haben-Kz | S = Soll (Einnahme), H = Haben (Ausgabe) | `S` |
| C | WKZ Umsatz | Währungscode | `EUR` |
| D | Kurs | Wechselkurs (leer bei EUR) | |
| E | Basis-Umsatz | Basisbetrag (leer bei EUR) | |
| F | WKZ Basis-Umsatz | Basiswährung (leer bei EUR) | |
| G | Konto | SKR03-Kontonummer | `8400` |
| H | Gegenkonto | Gegenkonto | `1200` |
| I | BU-Schlüssel | Steuerschlüssel | `3` |
| J | Belegdatum | Belegdatum (TTMM) | `1502` |
| K | Belegfeld 1 | Referenzfeld 1 | `RE-2026-001` |
| L | Belegfeld 2 | Referenzfeld 2 | |
| M | Skonto | Skonto | |
| N | Buchungstext | Buchungsbeschreibung | `Etsy Order #123` |

> **CSV-Formel-Injection**: Freitext-Spalten (Buchungstext, Beleginfo-Name/Beschreibung, Belegfelder) können extern beeinflusste Werte enthalten (z. B. Käufer-/Zahlernamen aus Marktplatz-/PayPal-Sync). Beginnt ein solcher Wert mit `=`, `+`, `-`, `@`, Tab oder CR, stellt der Export ihm ein `'` voran, damit Excel/LibreOffice/DATEV ihn als Text statt als Formel behandelt. Strukturierte Spalten (Beträge, Datum, Konten) bleiben unangetastet, bleiben also maschinenlesbar.

## Gegenkonto-Ableitung

Das Gegenkonto wird aus der Transaktionsquelle abgeleitet:

| Quelle | Gegenkonto | Kontoname |
|--------|-----------|-----------|
| DKB | 1200 | Bank |
| Finom | 1200 | Bank |
| PayPal | 1210 | PayPal |
| Etsy | 1590 | Durchlaufende Posten |
| Amazon | 1590 | Durchlaufende Posten |
| Shopify | 1590 | Durchlaufende Posten |
| Stripe | 1590 | Durchlaufende Posten |

Individuelle Zuordnungen können über die `check_accounts`-Tabelle in der Datenbank konfiguriert werden.

## BU-Schlüssel (Steuerschlüssel)

Der BU-Schlüssel bestimmt die Umsatzsteuer-Behandlung:

| Schlüssel | Satz | Typ | Verwendung |
|-----------|------|-----|------------|
| 2 | 7% | USt (Umsatzsteuer) | Einnahmen mit ermäßigtem Satz |
| 3 | 19% | USt (Umsatzsteuer) | Einnahmen mit Regelsatz |
| 8 | 7% | VSt (Vorsteuer) | Ausgaben mit ermäßigtem Satz |
| 9 | 19% | VSt (Vorsteuer) | Ausgaben mit Regelsatz |

Der BU-Schlüssel ist auf jedem SKR03-Konto hinterlegt und wird beim Export automatisch angewendet. Mehrwertsteuerbeträge (Netto + Steuer) werden aus dem Bruttobetrag berechnet.

## Soll/Haben-Logik

- **Einnahmen** (positiver Betrag): `S` (Soll) — das Geld kommt rein
- **Ausgaben** (negativer Betrag): `H` (Haben) — das Geld geht raus

Der exportierte Betrag ist immer positiv. Das S/H-Kennzeichen bestimmt die Richtung.

## Filter

Exporte können gefiltert werden nach:

- **Datumsbereich**: `date_from` / `date_to`
- **Kontierungsstatus**: Standardmäßig werden nur kontierte Transaktionen exportiert
- **Private Transaktionen**: Standardmäßig ausgeschlossen (`is_private = false`)

## API-Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/api/v1/datev` | POST | Export als JSON (zur Vorschau) |
| `/api/v1/datev/download` | POST | Export als CSV-Datei |
| `/api/v1/datev/preview` | POST | Vorschau mit begrenzten Zeilen |
| `/api/v1/datev/validate` | POST | Konfiguration validieren |
| `/api/v1/datev/history` | GET | Export-Historie |

## Konfiguration

Die DATEV-Konfiguration wird pro Benutzer in der Datenbank gespeichert:

```json
{
  "beraternummer": "1234567",
  "mandantennummer": "12345",
  "wirtschaftsjahr_beginn": "2026-01-01",
  "sachkontenlaenge": 4
}
```

Konfiguriere über die Einstellungen-Seite oder `PUT /api/v1/settings/datev`.
