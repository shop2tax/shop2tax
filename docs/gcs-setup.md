# Google Cloud Storage einrichten

Komplette Anleitung zur Einrichtung von GCS als Belegspeicher in shop2tax.
GCS bietet GoBD-konformen WORM-Speicher (Write-Once-Read-Many) für Belegdateien.

## Hintergrund: GoBD und WORM

**GoBD** (Grundsätze zur ordnungsmäßigen Führung und Aufbewahrung von Büchern, Aufzeichnungen und Unterlagen in elektronischer Form sowie zum Datenzugriff) ist eine Verwaltungsvorschrift des Bundesfinanzministeriums. Sie regelt, wie digitale Buchführungsunterlagen aufbewahrt werden müssen. Für shop2tax relevant: Belege (Rechnungen, Quittungen) müssen **10 Jahre unveränderbar** gespeichert werden.

**WORM** (Write-Once-Read-Many) ist ein Speicherprinzip, bei dem Dateien nach dem Schreiben nicht mehr verändert oder gelöscht werden können — wie ein physischer Ordner, aus dem man keine Seiten entfernen kann. GCS unterstützt WORM über Bucket-Retention-Policies: eine einmal geschriebene Datei kann für die konfigurierte Aufbewahrungsdauer (hier 3653 Tage = 10 Jahre) weder überschrieben noch gelöscht werden.

**DSGVO** (Datenschutz-Grundverordnung) verlangt, dass personenbezogene Daten (wie Rechnungen mit Namen und Adressen) innerhalb der EU gespeichert werden. Deshalb muss der GCS-Bucket in einer europäischen Region liegen (`europe-west3` = Frankfurt).

## Platzhalter

Ersetze diese Werte in der Anleitung durch deine tatsächlichen Werte:

| Platzhalter | Beispiel | Beschreibung |
|-------------|----------|--------------|
| `YOUR_PROJECT_ID` | `meine-buchhaltung` | GCP-Projekt-ID (global eindeutig) |
| `YOUR_BUCKET_NAME` | `meine-belege` | GCS-Bucket-Name (global eindeutig) |
| `YOUR_SA_NAME` | `receipt-storage` | Service-Account-Name (projektbezogen) |
| `YOUR_ORG_ID` | `123456789012` | Google Workspace Organisations-ID |

## Voraussetzungen

- Google Cloud Account
- `gcloud` CLI installiert ([Installationsanleitung](https://cloud.google.com/sdk/docs/install))
- Docker + Docker Compose

## 1. gcloud CLI authentifizieren

```bash
gcloud auth login
```

Dies öffnet einen Browser zur Google-Anmeldung. Nach der Anmeldung setze dein Projekt:

```bash
gcloud config set project YOUR_PROJECT_ID
```

## 2. GCP-Projekt erstellen (überspringen falls vorhanden)

**Console:** https://console.cloud.google.com/projectcreate

**CLI:**
```bash
gcloud projects create YOUR_PROJECT_ID --name="Dein Projektname"
gcloud config set project YOUR_PROJECT_ID
```

### Abrechnung aktivieren

Ein Rechnungskonto ist erforderlich, bevor du Buckets erstellen oder GCS-APIs nutzen kannst.

**Console:** https://console.cloud.google.com/billing/linkedaccount

Falls noch kein Rechnungskonto existiert, erstelle zuerst eines: https://console.cloud.google.com/billing/create

**CLI:**
```bash
# Rechnungskonten auflisten
gcloud billing accounts list

# Rechnungskonto mit Projekt verknüpfen
gcloud billing projects link YOUR_PROJECT_ID --billing-account=YOUR_BILLING_ACCOUNT_ID
```

### Erforderliche APIs aktivieren

```bash
gcloud services enable storage.googleapis.com
gcloud services enable iam.googleapis.com
```

## 3. GCS-Bucket erstellen

Der Bucket muss zwei Compliance-Anforderungen erfüllen:
- **DSGVO**: Region muss in Europa liegen
- **GoBD**: Aufbewahrungsrichtlinie von 10 Jahren (3653 Tage)

**Console:** https://console.cloud.google.com/storage/create-bucket

**CLI:**
```bash
# Bucket in EU-Region erstellen
gcloud storage buckets create gs://YOUR_BUCKET_NAME \
  --location=europe-west3 \
  --uniform-bucket-level-access

# 10-Jahres-Aufbewahrungsrichtlinie setzen (GoBD-Konformität)
gcloud storage buckets update gs://YOUR_BUCKET_NAME \
  --retention-period=3653d
```

**Überprüfen:**
```bash
gcloud storage buckets describe gs://YOUR_BUCKET_NAME \
  --format="table(location, retentionPolicy.retentionPeriod)"
```

Erwartete Ausgabe: Location `EUROPE-WEST3`, Retention Period `315331200` (Sekunden = 3653 Tage).

## 4. Service-Account erstellen

Ein Service-Account-Key bietet permanente Credentials, die nicht ablaufen (im Gegensatz zu `gcloud auth application-default login`, das täglich abläuft).

**Console:** https://console.cloud.google.com/iam-admin/serviceaccounts/create

**CLI:**
```bash
gcloud iam service-accounts create YOUR_SA_NAME \
  --display-name="shop2tax Speicherzugriff"
```

### Bucket-Berechtigungen erteilen

Der Service-Account benötigt drei Rollen:
- `storage.objectCreator` — Upload (Belege hochladen)
- `storage.objectViewer` — Download, Existenzprüfung (Belege abrufen)
- `storage.legacyBucketReader` — Bucket-Metadaten lesen (Region, Aufbewahrungsrichtlinie) für Startup-Validierung

> **Bewusst kein `storage.objectAdmin`!** Der SA kann Objekte erstellen und lesen, aber nicht löschen. Das ist WORM-konform (Write-Once-Read-Many) und schützt vor versehentlichem oder böswilligem Löschen — selbst bei Key-Diebstahl.

```bash
# Upload (Belege hochladen)
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET_NAME \
  --member="serviceAccount:YOUR_SA_NAME@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectCreator"

# Download + Existenzprüfung (Belege abrufen)
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET_NAME \
  --member="serviceAccount:YOUR_SA_NAME@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# Bucket-Metadaten lesen (Startup-Validierung)
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET_NAME \
  --member="serviceAccount:YOUR_SA_NAME@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.legacyBucketReader"
```

### Projekt-Berechtigung erteilen

Der Service-Account benötigt außerdem `serviceusage.serviceUsageConsumer` auf Projektebene für API-Aufrufe:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SA_NAME@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/serviceusage.serviceUsageConsumer"
```

## 5. Service-Account-Key erstellen

### Organisations-Policy blockiert?

Google Workspace Organisationen blockieren oft standardmäßig die Erstellung von Service-Account-Keys.
Falls du `"Key creation is not allowed on this service account"` erhältst, musst du die Organisations-Policy temporär deaktivieren.

**Prüfen ob du betroffen bist:**
```bash
gcloud org-policies describe iam.disableServiceAccountKeyCreation --project=YOUR_PROJECT_ID
```

**Temporär deaktivieren (erfordert Organization Policy Administrator Rolle):**

```bash
# Deine Organisations-ID finden
gcloud organizations list

# Dir selbst Org Policy Admin geben (falls nötig)
gcloud organizations add-iam-policy-binding YOUR_ORG_ID \
  --member="user:deine-email@example.com" \
  --role="roles/orgpolicy.policyAdmin"

# Org Policy API aktivieren
gcloud services enable orgpolicy.googleapis.com --project=YOUR_PROJECT_ID

# Key-Erstellungs-Einschränkung deaktivieren
gcloud org-policies set-policy --project=YOUR_PROJECT_ID /dev/stdin <<'EOF'
name: projects/YOUR_PROJECT_ID/policies/iam.disableServiceAccountKeyCreation
spec:
  rules:
  - enforce: false
EOF

# Auch die managed constraint deaktivieren (neuere Version)
gcloud org-policies set-policy --project=YOUR_PROJECT_ID /dev/stdin <<'EOF'
name: projects/YOUR_PROJECT_ID/policies/iam.managed.disableServiceAccountKeyCreation
spec:
  rules:
  - enforce: false
EOF
```

**Console-Alternative:**
1. Gehe zu https://console.cloud.google.com/iam-admin/orgpolicies/iam-disableServiceAccountKeyCreation?project=YOUR_PROJECT_ID
2. Klicke "Richtlinie verwalten"
3. Regel hinzufügen → Erzwingung: Aus → Speichern

### Key erstellen

```bash
mkdir -p ~/.config/shop2tax

gcloud iam service-accounts keys create ~/.config/shop2tax/gcs-service-account.json \
  --iam-account=YOUR_SA_NAME@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --project=YOUR_PROJECT_ID
```

**Organisations-Policy nach Key-Erstellung wieder aktivieren:**
```bash
gcloud org-policies delete iam.disableServiceAccountKeyCreation --project=YOUR_PROJECT_ID
gcloud org-policies delete iam.managed.disableServiceAccountKeyCreation --project=YOUR_PROJECT_ID
```

### Key-Datei schützen

Die Key-Datei darf niemals in Git eingecheckt werden. Sie ist bereits durch `.gitignore`-Muster abgedeckt, aber überprüfe:

```bash
# Sollte zeigen: Berechtigung -rw-------
ls -la ~/.config/shop2tax/gcs-service-account.json

# Berechtigungen einschränken falls nötig
chmod 600 ~/.config/shop2tax/gcs-service-account.json
```

## 6. Umgebungsvariablen konfigurieren

Mit dotenvx (verschlüsselte `.env`):

```bash
dotenvx set STORAGE_BACKEND gcs
dotenvx set GCS_BUCKET_NAME dein-bucket-name
dotenvx set GOOGLE_CLOUD_PROJECT dein-projekt-id
dotenvx set GOOGLE_SERVICE_ACCOUNT_KEY /pfad/zu/gcs-service-account.json
```

Oder manuell in `.env`:

```bash
STORAGE_BACKEND=gcs
GCS_BUCKET_NAME=dein-bucket-name
GOOGLE_CLOUD_PROJECT=dein-projekt-id
GOOGLE_SERVICE_ACCOUNT_KEY=/Users/du/.config/shop2tax/gcs-service-account.json
```

## 7. Anwendung starten

```bash
make dev-build
```

Beim Start validiert die API:
1. GCS-Authentifizierung (Service-Account-Key ist gültig)
2. Bucket-Region beginnt mit `europe` (DSGVO)
3. Bucket hat eine Aufbewahrungsrichtlinie (GoBD)

Erfolgreiche Ausgabe in den Logs:
```
Storage: gcs (WORM enabled, EUROPE-WEST3, retention=3653 days)
```

## 8. Projekt absichern (Kostenschutz)

> **Hintergrund:** Im Februar 2026 teilte ein Entwickler auf Reddit (r/googlecloud), dass sein Team angeblich $82.000 in 48 Stunden durch einen kompromittierten Gemini API Key verloren hat — bei einem normalen Monatsverbrauch von $180. Ob die Geschichte stimmt und wie genau es dazu kam, ist nicht verifizierbar. Aber das Szenario ist technisch plausibel, und die Vorkehrungen dagegen dauern nur 10 Minuten.

### Unnötige APIs deaktivieren

GCP-Projekte haben oft APIs aktiviert, die du nicht brauchst. Jede aktive API ist ein potenzieller Kostentreiber bei Key-Diebstahl. shop2tax braucht **nur diese APIs**:

| API | Zweck |
|-----|-------|
| Cloud Storage API | Belegspeicher (GoBD-WORM) |
| IAM API | Service-Account-Verwaltung |
| Service Usage API | Wird von GCS intern gebraucht |

**Alles andere deaktivieren**, insbesondere:
- **Generative Language API / Vertex AI** — KI-Kosten können in Stunden explodieren
- **BigQuery** (alle Varianten) — Datenverarbeitung, teuer bei Missbrauch
- **Cloud SQL** — Datenbank-as-a-Service (du nutzt Postgres in Docker)
- **Compute Engine** — VM-Instanzen

**Prüfen und aufräumen:**

**Console:** https://console.cloud.google.com/apis/dashboard

**CLI:**
```bash
# Alle aktivierten APIs auflisten
gcloud services list --enabled --project=YOUR_PROJECT_ID

# Einzelne API deaktivieren
gcloud services disable bigquery.googleapis.com --project=YOUR_PROJECT_ID
gcloud services disable generativelanguage.googleapis.com --project=YOUR_PROJECT_ID
```

### Budget-Alert einrichten

GCS-Kosten für shop2tax liegen typischerweise unter 1 €/Monat. Ein Budget-Alert warnt dich frühzeitig bei unerwartetem Verbrauch.

**Console:** https://console.cloud.google.com/billing/budgets

Erstelle ein Budget:
- **Betrag:** 5 € (großzügig für reinen Storage-Betrieb)
- **Schwellenwerte:** 50%, 80%, 100%
- **Benachrichtigungen:** E-Mail an Abrechnungsadministratoren UND Projektinhaber aktivieren

**CLI:**
```bash
gcloud billing budgets create \
  --billing-account=YOUR_BILLING_ACCOUNT_ID \
  --display-name="shop2tax Safety Net" \
  --budget-amount=5.00EUR \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.8 \
  --threshold-rule=percent=1.0
```

> **Wichtig:** Google-Budgets sind Benachrichtigungen, keine Hard Caps. Sie stoppen den Verbrauch nicht automatisch. Die eigentliche Absicherung ist das Deaktivieren unnötiger APIs (siehe oben).

### AI-API-Keys separat verwalten

shop2tax unterstützt KI-basierte Belegextraktion (Gemini, OpenAI, Anthropic). Diese Keys gehören **nicht** in dein GCS-Projekt:

- **OpenAI**: Hat eingebaute Spending Limits unter https://platform.openai.com/settings/organization/limits — setze ein Hard Cap (z.B. 5 $/Monat). OpenAI stoppt tatsächlich bei Erreichen.
- **Anthropic**: Spending Limits unter https://console.anthropic.com/settings/limits
- **Gemini (AI Studio)**: Keys unter https://aistudio.google.com/apikey — ohne Billing im AI-Studio-Projekt sind nur Free-Tier-Anfragen möglich. Wenn du ein Billing-Konto verknüpfst, unbedingt Quotas setzen.

### Service-Account-Key schützen

Die Key-Datei (`gcs-service-account.json`) ist der sensibelste Teil des Setups:

- **Niemals in Git committen** — auch nicht verschlüsselt in `.env` (dort gehört nur der Pfad rein)
- **Dateiberechtigungen einschränken:** `chmod 600`
- **Swap-Dateien löschen** — Editoren wie Vim erstellen `.env.swp`-Dateien mit unverschlüsseltem Inhalt
- **Key regelmäßig rotieren** — alten Key löschen, neuen erstellen:

```bash
# Aktive Keys auflisten
gcloud iam service-accounts keys list \
  --iam-account=YOUR_SA_NAME@YOUR_PROJECT_ID.iam.gserviceaccount.com

# Neuen Key erstellen
gcloud iam service-accounts keys create ~/.config/shop2tax/gcs-service-account-new.json \
  --iam-account=YOUR_SA_NAME@YOUR_PROJECT_ID.iam.gserviceaccount.com

# Alten Key löschen (KEY_ID aus der Liste oben)
gcloud iam service-accounts keys delete KEY_ID \
  --iam-account=YOUR_SA_NAME@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

### Sicherheits-Checkliste

Nach dem Setup sollte dein Projekt diesen Zustand haben:

- [ ] Nur Storage + IAM + Service Usage APIs aktiviert
- [ ] Budget-Alert bei 5 € eingerichtet
- [ ] Service-Account hat nur Storage-Rollen auf Bucket-Ebene + `serviceUsageConsumer` auf Projekt-Ebene (keine Admin- oder Editor-Rollen)
- [ ] Key-Datei mit `chmod 600` geschützt
- [ ] Keine `.swp`- oder Backup-Dateien mit Secrets im Projektverzeichnis
- [ ] AI-API-Keys (falls genutzt) haben Spending Limits beim jeweiligen Anbieter

## Fehlerbehebung

### `GCS authentication expired`

Du verwendest Application Default Credentials statt eines Service-Account-Keys.
Folge den Schritten 4-6 oben, um einen Service-Account-Key zu erstellen.

### `does not have storage.buckets.get access`

Dem Service-Account fehlen Bucket-Berechtigungen:
```bash
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET_NAME \
  --member="serviceAccount:YOUR_SA_NAME@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.legacyBucketReader"
```

### `does not have serviceusage.services.use access`

Dem Service-Account fehlt die Projekt-Berechtigung:
```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SA_NAME@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/serviceusage.serviceUsageConsumer"
```

### `bucket is in 'us-central1', expected 'europe-*'`

Der Bucket wurde in einer Nicht-EU-Region erstellt. GCS-Buckets können nach der Erstellung nicht verschoben werden.
Erstelle einen neuen Bucket in einer EU-Region (`europe-west3` empfohlen für Deutschland).

### `no retention policy`

```bash
gcloud storage buckets update gs://YOUR_BUCKET_NAME --retention-period=3653d
```

### `Key creation is not allowed on this service account`

Die Organisations-Policy blockiert die Key-Erstellung. Siehe [Abschnitt 5](#5-service-account-key-erstellen) für die temporäre Deaktivierung.

### Startup-Crash ohne Fehler in den Logs

Falls der API-Container ohne Fehlerausgabe crasht, prüfe dass `main.py` den Startup-Error-Handler enthält.
Der Lifespan-Handler gibt Exceptions direkt auf stderr aus, um Uvicorns stilles Crash-Verhalten zu umgehen.

## Architektur

```
Docker-Container (API)
├── GOOGLE_APPLICATION_CREDENTIALS=/secrets/google-credentials.json
├── Volume-Mount: ${GOOGLE_SERVICE_ACCOUNT_KEY} → /secrets/google-credentials.json (read-only)
└── Python GCS-Client liest Credentials automatisch via ADC

Startup-Validierung:
  config.py → validiert STORAGE_BACKEND + GCS_BUCKET_NAME
  gcs_backend.py → validiert Auth, EU-Region, Aufbewahrungsrichtlinie
  main.py → blockiert Nicht-WORM-Backends in Produktion
```

## Erforderliche IAM-Rollen (Zusammenfassung)

| Rolle | Ebene | Zweck |
|-------|-------|-------|
| `storage.objectCreator` | Bucket | Upload (Belege hochladen) |
| `storage.objectViewer` | Bucket | Download, Existenzprüfung |
| `storage.legacyBucketReader` | Bucket | Bucket-Metadaten für Startup-Validierung |
| `serviceusage.serviceUsageConsumer` | Projekt | GCS-API-Aufrufe durchführen |

> **Kein `storage.objectAdmin`** — bewusst aufgeteilt in Creator + Viewer für WORM-Konformität (kein Löschen möglich).
