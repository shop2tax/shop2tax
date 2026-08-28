# Etsy CSV-Import

## CSV herunterladen

1. **Etsy Shop Manager** öffnen → **Finanzen** → **Monatliche Abrechnung**
2. Den gewünschten Monat auswählen
3. **CSV herunterladen** klicken
4. Die Datei enthält alle Transaktionstypen (Verkäufe, Gebühren, Erstattungen, Steuern, Auszahlungen)

## Import in shop2tax

### Voraussetzung: Etsy-Quelle anlegen

1. **Einstellungen** → **Bank-Quellen** → **Quelle hinzufügen**
2. Name: `Etsy` (oder beliebig)
3. Typ: `Marktplatz (CSV)`
4. Buchungskonto: `1201` (Etsy Payments, virtuelles Bankkonto)
5. **Speichern**, dann Quelle bearbeiten:
   - Parser: `Etsy`
   - USt-ID-Checkbox: Aktivieren, wenn du eine USt-ID bei Etsy hinterlegt hast

### CSV importieren

1. **Import** → **Marktplatz Import** → Etsy-Quelle auswählen
2. CSV-Datei hochladen → **Weiter**
3. Der Etsy-Parser erkennt automatisch alle Transaktionstypen:
   - **Sale**: Verkaufserlöse (SKR03: 8400/8300)
   - **Listing Fee / Transaction Fee / Processing Fee**: Etsy-Gebühren (SKR03: 3165/3125)
   - **Refund**: Erstattungen
   - **Sales Tax**: Durchlaufende Steuern (US Sales Tax)
   - **Payout**: Auszahlungen auf Bankkonto (Geldtransit)
4. Vorschau prüfen → **Importieren**
5. Nach dem Import: **Etsy-PDF als Beleg hochladen** (monatliche Rechnung)

### Billbee-Enrichment (optional)

Wenn ein Billbee-Store mit der Etsy-Quelle verknüpft ist, werden Verkaufszeilen automatisch mit Kundennamen aus Billbee angereichert.

## Steuerliche Szenarien

Die korrekte Verbuchung hängt von zwei Faktoren ab:

| Szenario | Kleinunternehmer? | USt-ID bei Etsy? | Erlöskonto | RC-Behandlung |
|----------|-------------------|-------------------|------------|---------------|
| **A** | Ja | Ja | 8400 (steuerfrei) | RC-USt ohne VSt-Abzug (BU 95) |
| **B** | Ja | Nein | 8400 (steuerfrei) | Kein RC (Etsy führt USt ab) |
| **C** | Nein | Ja | 8400 (19%) | RC-USt mit VSt-Abzug (BU 94) |
| **D** | Nein | Nein | 8400 (19%) | Kein RC |

### Reverse Charge (§13b UStG)

Etsy Ireland UC (IE9777587C) berechnet Gebühren an EU-Verkäufer. Bei hinterlegter USt-ID gilt Reverse Charge:
- **Kleinunternehmer**: USt-Schuld ohne Vorsteuerabzug → erhöht die effektive Gebührenbelastung
- **Regelbesteuert**: USt-Schuld mit Vorsteuerabzug → kostenneutral

Die RC-USt wird in der UStVA gemeldet (Kz. 46/47, ggf. Kz. 67).

## Geldtransit-Konzept

Etsy-Transaktionen werden auf Konto **1201** (Etsy Payments) gebucht — ein virtuelles Bankkonto. Wenn Etsy Geld auf dein Bankkonto auszahlt:

1. Etsy-CSV: Payout-Buchung auf 1201 (Haben)
2. Bank-CSV: Eingang auf 1200 (Soll)
3. Beide Buchungen matchen → Konto 1201 sollte auf Null stehen

Der Saldo von 1201 zeigt nicht-ausgezahlte Beträge bei Etsy.
