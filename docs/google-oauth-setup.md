# Google OAuth einrichten

Diese Anleitung beschreibt die Einrichtung von Google OAuth für Mehrbenutzerbetrieb. Ohne OAuth läuft shop2tax im **Local Mode** (kein Login erforderlich).

## Wann brauche ich Google OAuth?

| Szenario | OAuth nötig? |
|----------|--------------|
| Einzelnutzer, lokale Nutzung | ❌ Nein (Local Mode) |
| Mehrere Benutzer mit eigenem Login | ✅ Ja |
| Öffentlich erreichbare Installation | ✅ Ja |
| Audit-Trail pro Benutzer | ✅ Ja |

## Übersicht

```
┌──────────────────────────────────────────────────────────────────┐
│                     Google Cloud Console                          │
├──────────────────────────────────────────────────────────────────┤
│  1. Projekt erstellen (oder vorhandenes wählen)                   │
│  2. OAuth-Zustimmungsbildschirm konfigurieren                     │
│  3. OAuth 2.0 Credentials erstellen                               │
│  4. Redirect-URI hinzufügen                                       │
│  5. Client ID + Secret in .env eintragen                          │
└──────────────────────────────────────────────────────────────────┘
```

## Schritt 1: Google Cloud Projekt

1. Öffne die [Google Cloud Console](https://console.cloud.google.com/)
2. Klicke oben auf das Projekt-Dropdown
3. Wähle **Neues Projekt** oder ein bestehendes Projekt

> 💡 Falls du bereits ein Projekt für GCS-Belegspeicherung hast, kannst du dasselbe Projekt verwenden.

## Schritt 2: OAuth-Zustimmungsbildschirm

1. Gehe zu **APIs & Dienste → OAuth-Zustimmungsbildschirm**
   - Direktlink: https://console.cloud.google.com/apis/credentials/consent
2. Wähle den Nutzertyp:
   - **Intern**: Nur für Nutzer deiner Google Workspace Organisation
   - **Extern**: Für alle Google-Konten (erfordert Verifizierung für >100 Nutzer)
3. Klicke **Erstellen**

### App-Informationen ausfüllen

| Feld | Wert |
|------|------|
| App-Name | `shop2tax` (oder dein Firmenname) |
| Support-E-Mail | Deine E-Mail-Adresse |
| App-Logo | Optional |
| App-Domain | Optional |
| Entwickler-Kontakt | Deine E-Mail-Adresse |

### Bereiche (Scopes)

Klicke **Bereiche hinzufügen oder entfernen** und wähle:

| Bereich | Beschreibung |
|---------|--------------|
| `.../auth/userinfo.email` | E-Mail-Adresse lesen |
| `.../auth/userinfo.profile` | Name und Profilbild lesen |
| `openid` | OpenID Connect |

Diese Bereiche sind "nicht sensibel" und erfordern keine App-Verifizierung.

### Testnutzer (nur bei "Extern")

Falls du "Extern" gewählt hast:
1. Klicke **Testnutzer hinzufügen**
2. Trage die E-Mail-Adressen aller Nutzer ein, die sich einloggen dürfen
3. Solange die App nicht verifiziert ist, können nur Testnutzer sich anmelden

## Schritt 3: OAuth 2.0 Credentials erstellen

1. Gehe zu **APIs & Dienste → Anmeldedaten**
   - Direktlink: https://console.cloud.google.com/apis/credentials
2. Klicke **+ Anmeldedaten erstellen → OAuth-Client-ID**
3. Wähle Anwendungstyp: **Webanwendung**
4. Name: `shop2tax` (oder beliebig)

### Autorisierte Redirect-URIs

Füge die Redirect-URI hinzu, unter der shop2tax erreichbar ist:

| Umgebung | Redirect-URI |
|----------|--------------|
| Entwicklung | `http://127.0.0.1:3002/auth/google` |
| Produktion | `https://deine-domain.de/auth/google` |

> ⚠️ **Wichtig**: Die URI muss exakt übereinstimmen, inkl. Protokoll und Port. `localhost` funktioniert nicht — verwende `127.0.0.1`.

5. Klicke **Erstellen**
6. Notiere **Client-ID** und **Clientschlüssel**

## Schritt 4: Umgebungsvariablen setzen

Trage die Credentials in deine `.env`-Datei ein:

```bash
# Google OAuth
GOOGLE_CLIENT_ID=123456789-abcdefg.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxxxxxxxxxx

# Für Nuxt
NUXT_OAUTH_GOOGLE_CLIENT_ID=123456789-abcdefg.apps.googleusercontent.com
NUXT_OAUTH_GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxxxxxxxxxx
```

> 💡 Beide Variablenpaare müssen denselben Wert haben. `GOOGLE_CLIENT_ID` wird vom API-Backend gelesen, `NUXT_OAUTH_*` vom Frontend.

## Schritt 5: App neu starten

```bash
docker compose down
docker compose up
```

Nach dem Neustart:
1. Öffne http://127.0.0.1:3002
2. Du siehst den Login-Button
3. Klicke auf "Mit Google anmelden"
4. Wähle dein Google-Konto

## Fehlerbehebung

### "redirect_uri_mismatch"

Die Redirect-URI in der Google Console stimmt nicht mit der App überein.

**Lösung:**
1. Öffne die Credentials in der Google Console
2. Prüfe die "Autorisierten Redirect-URIs"
3. Stelle sicher, dass die URI exakt übereinstimmt:
   - Protokoll: `http` vs `https`
   - Host: `127.0.0.1` vs `localhost`
   - Port: `:3002` vs ohne Port
   - Pfad: `/auth/google` (exakt)

### "App nicht verifiziert" Warnung

Bei externen Apps ohne Verifizierung erscheint eine Warnung.

**Für Testnutzer:**
1. Klicke "Erweitert"
2. Klicke "Zu [App-Name] wechseln (unsicher)"

**Für Produktivbetrieb:**
Beantrage die App-Verifizierung in der Google Console (OAuth-Zustimmungsbildschirm → Veröffentlichen).

### "access_denied"

Der Nutzer hat den Zugriff verweigert oder ist nicht als Testnutzer eingetragen.

**Lösung:**
1. Gehe zu OAuth-Zustimmungsbildschirm → Testnutzer
2. Füge die E-Mail-Adresse hinzu
3. Versuche es erneut

### Login funktioniert, aber API gibt 401

Die API-Container haben `GOOGLE_CLIENT_ID` nicht erhalten.

**Prüfen:**
```bash
docker compose exec api env | grep GOOGLE
```

**Lösung:**
Stelle sicher, dass `GOOGLE_CLIENT_ID` in `.env` gesetzt ist und der Container neu gestartet wurde.

## Produktion

Für den Produktivbetrieb:

1. Füge die Produktions-URI zu den Redirect-URIs hinzu:
   ```
   https://buchhaltung.deine-domain.de/auth/google
   ```

2. Aktualisiere `.env`:
   ```bash
   DOMAIN=buchhaltung.deine-domain.de
   ```

3. Für mehr als 100 Nutzer: Beantrage die App-Verifizierung

## Zurück zu Local Mode

Falls du OAuth deaktivieren möchtest:

1. Kommentiere die Google-Variablen in `.env` aus:
   ```bash
   # GOOGLE_CLIENT_ID=...
   # GOOGLE_CLIENT_SECRET=...
   # NUXT_OAUTH_GOOGLE_CLIENT_ID=...
   # NUXT_OAUTH_GOOGLE_CLIENT_SECRET=...
   ```

2. Starte neu:
   ```bash
   docker compose down
   docker compose up
   ```

Die App läuft wieder im Local Mode — kein Login erforderlich.
