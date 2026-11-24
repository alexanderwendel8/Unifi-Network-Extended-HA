# Changelog

Alle nennenswerten Änderungen an dieser Integration. Neue Einträge kommen zuerst unter
„Unreleased“; beim nächsten Release wird dieser Abschnitt zur Versionsnummer.

## Unreleased

### Entwicklung

- Neuer Workflow `api-mirror.yml`: spiegelt jeden Montag die offiziellen Spezifikationen der
  UniFi Network API von developer.ui.com nach `docs/api/network/<Version>/openapi.json`
  (Übersicht in `docs/api/README.md`). Vorhandene Versionen werden nie geändert oder gelöscht.
  Logik in `.github/scripts/mirror_api.py`, mit Tests.
- `update-check.yml` legt ein Issue an, wenn eine neuere API-Version gespiegelt ist als die,
  gegen die entwickelt wird (`docs/unifi-network-api.openapi.json`).

### Behoben

- Bei Verbindungsfehlern (Zeitüberschreitung, Verbindung abgelehnt) blieb die Meldung
  „Error fetching … data:“ im Log leer. Jetzt stehen Anfrage und Fehlerart darin, z. B.
  `GET /v1/sites/…/devices: cannot connect (timeout)`, weiterhin ohne Host und API-Key. Die
  Debug-Meldung dazu enthielt bisher den Fehlertext von aiohttp und damit unter Umständen den
  Host; sie entfällt.

## 0.3.0

Optionen laden über das eingebaute Neuladen von Home Assistant; dafür ist jetzt
**Home Assistant 2025.8.0 oder neuer** nötig. Dazu eine wöchentliche automatische Prüfung
externer Komponenten. Am echten UniFi-Netz getestet ist bisher 0.2.0; 0.3.0 ist durch die
automatischen Tests (Home Assistant 2025.8.0 bis aktuell) geprüft.

### Geändert
- Optionen nutzen das automatische Neuladen von Home Assistant (`OptionsFlowWithReload`) statt
  eines eigenen Update-Listeners. Eine Änderung von Abrufintervall oder „Clients verfolgen“ wirkt
  weiterhin sofort und lädt den Eintrag genau einmal neu; „Neu konfigurieren“ und die erneute
  Anmeldung laden ebenfalls genau einmal neu. Damit entfällt die Warnung „has an update listener
  and should use it for scheduling a reload“, die Home Assistant seit 2026.6 bei „Neu konfigurieren“
  und erneuter Anmeldung ins Log schreibt.
- Mindestversion von Home Assistant auf **2025.8.0** angehoben (erste Version mit
  `OptionsFlowWithReload`); `hacs.json`, README, `CLAUDE.md` und Test-Workflow angepasst.

### Dokumentation

- README: Getestete Version auf 0.2.0 aktualisiert (Statuszeile und Tabelle „Getestete Geräte“).

### Entwicklung

- Neuer Workflow `update-check.yml`: prüft jeden Montag GitHub Actions, gepinnte Python-Pakete
  und neue Home-Assistant-Releases (samt Python-Mindestversion) und legt für jede veraltete
  Komponente ein Issue mit dem Label `aktualisierung` an. Ist die Komponente wieder aktuell,
  wird das Issue geschlossen. Logik in `.github/scripts/check_updates.py`, mit Tests.
- `ruff` prüft auch `.github/scripts`.
- `ruff` auf 0.17.6 aktualisiert (#34).
- `CLAUDE.md`: Offene Issues mit dem Label `aktualisierung` werden zu Beginn jeder Sitzung
  geprüft; abgearbeitet werden sie nur nach Rückfrage.

## 0.2.0

Aufräumen und robustere Einrichtung: Geräte, die UniFi nicht mehr meldet, und Client-Tracker
nach 180 Tagen ohne Verbindung werden entfernt; die Host-Eingabe akzeptiert IPv6-Adressen und wird
bereinigt; kein doppeltes Neuladen mehr nach „Neu konfigurieren“.

### Geändert
- Device-Tracker von Clients, die 180 Tage nicht verbunden waren, werden automatisch entfernt,
  auch eingeschaltete (Prüfung beim Start und täglich). Ein nur für den Tracker angelegtes Gerät
  wird mit entfernt, Geräte anderer Integrationen bleiben erhalten. Der Zeitpunkt der letzten
  Verbindung wird pro Konfigurationseintrag gespeichert; bestehende Tracker starten ihre Frist
  mit dem ersten Start nach dem Update. Kommt der Client wieder, entsteht wieder ein Tracker.
- Beim Ausschalten von „Clients verfolgen“ werden auch die gespeicherten Verbindungszeiten
  gelöscht, beim Entfernen der Integration ihre Speicherdatei.

### Entitäten
- Geräte, die UniFi nicht mehr meldet, werden nach dem nächsten erfolgreichen Abruf samt Entitäten
  automatisch aus Home Assistant entfernt (auch beim Start); solche Geräte lassen sich zudem in der
  Oberfläche von Hand löschen. Offline-Geräte, Geräte mit ungültigen API-Daten (siehe 0.1.1) und das
  Standort-Gerät bleiben erhalten, ein erneut adoptiertes Gerät bekommt wieder Entitäten.

### Einrichtung
- Host als Hostname, IPv4- oder IPv6-Adresse; IPv6-Adressen werden in der URL korrekt in
  eckige Klammern gesetzt (z. B. `https://[fd00::1]:443/...`)
- Eingabe des Hosts wird bereinigt (Einrichten und Neu konfigurieren): Leerzeichen, `http://`/`https://`,
  abschließender `/` bzw. Pfad und eckige Klammern um IPv6-Adressen werden entfernt
- Ein Port in der Host-Eingabe (`unifi.local:8443`, `[fd00::1]:8443`) wird ins Feld Port übernommen
- Ungültige Hosts werden mit dem Fehler „Ungültiger Host“ abgelehnt, statt eine Verbindung zu versuchen
- Beim Neu konfigurieren bleiben die Eingaben nach einem Fehler im Formular erhalten

### Behoben
- Neu konfigurieren und erneute Anmeldung laden die Integration nur noch einmal statt zweimal neu.
  Der Listener für Optionen lädt nur noch bei geänderten Optionen neu.

### Dokumentation
- Changelog: Abschnitt „Unreleased“ für laufende Änderungen; Release-Ablauf entsprechend angepasst
- README: „Getestete Geräte“ nennt Version 0.1.1 und die UniFi-Network-Anwendung 11.0.104

### Entwicklung
- GitHub Actions auf Commit-SHA mit Versionskommentar festgelegt und aktualisiert (Node.js 24):
  `actions/checkout` v7.0.1, `actions/setup-python` v7.1.0, `softprops/action-gh-release` v3.0.4,
  `home-assistant/actions/hassfest` 2026.11.0, `hacs/action` 22.5.0
- Dependabot schlägt Updates der GitHub Actions wöchentlich als Pull Request vor

## 0.1.1

Wartungsrelease: robustere Verarbeitung der API-Daten, aktuelles Geräteregister und die
Version der UniFi-Network-Anwendung als Sensor.

### Neu
- **Standort:** Diagnose-Sensor *UniFi-Network-Version* mit der Version der
  UniFi-Network-Anwendung (`GET /v1/info`); dieselbe Version steht als Firmware-Version am
  Standort-Gerät und in den Diagnosedaten. Abfrage beim Start und danach stündlich; ein Fehler
  dabei verhindert den Start nicht, ein ungültiger API-Schlüssel startet die erneute Anmeldung.

### Behoben
- Firmware-Version und Name der UniFi-Geräte werden im Geräteregister von Home Assistant bei jedem
  Abruf aktualisiert, ohne die Integration neu zu laden. Ein in Home Assistant vergebener Name
  bleibt erhalten.
- Ein einzelner unerwartet aufgebauter Datensatz der UniFi-API (fehlendes Pflichtfeld oder
  unerwarteter Typ, z. B. nach einem Firmware-Update oder bei einem neuen Gerätetyp) macht
  nicht mehr alle Entitäten unverfügbar: Betroffene Standorte, Geräte, Clients, Ports und
  Funkbänder werden übersprungen, alle übrigen funktionieren weiter.
- Sind Statistik oder Details eines Geräts nicht auslesbar, betrifft das nur dieses Gerät.
- Ungültiges JSON (z. B. eine HTML-Seite statt einer API-Antwort) wird als unerwartete Antwort
  gemeldet, nicht mehr als „nicht erreichbar“.
- Übersprungene Daten werden je Ursache einmal als Warnung protokolliert, mit Endpunkt und
  Feldname, aber ohne API-Schlüssel, Host, Namen, MAC-Adressen oder IDs.

### Dokumentation
- README: Einleitung überarbeitet; neue Rubrik „Getestete Geräte“ (Home Assistant 2026.11.2,
  Geräte mit Firmware-Version, was am echten Netz geprüft ist und was nicht) (#14)
- README: Installation über den Marketplace (ab Home Assistant 2026.11), über HACS (bis 2026.10)
  und automatische Übernahme bestehender HACS-Installationen (#15)
- Entwicklungsregeln (`CLAUDE.md`): Fragen zu Home Assistant werden mit der offiziellen
  Home-Assistant-Dokumentation beantwortet (#16)

### Sonstiges
- Mindestversion Home Assistant 2025.3.0 (wie bisher in `hacs.json`) geprüft und in der README genannt;
  die CI testet jetzt 2025.3.0, 2026.2.3 und die aktuelle Version mit festgelegten Versionen von
  `pytest-homeassistant-custom-component` (aktuelle Version per Dependabot aktualisiert)

### Entwicklung
- Testabdeckung wird in der CI gemessen (Zeilen und Zweige), im Log und in der Zusammenfassung
  des Actions-Laufs angezeigt; der Lauf schlägt unter 97 % fehl
- Neue Tests für Fehlerpfade: Fehlertext aus der API-Antwort, ungültiger API-Schlüssel und
  unerwartete Fehler beim Abruf je Gerät, alle Standorte bereits eingerichtet, unbekanntes
  Uplink-Gerät, Funkbänder werden nur einmal angelegt (Abdeckung 97,1 % → 98,0 % auf allen drei
  getesteten Home-Assistant-Versionen)

## 0.1.0

Erstes Release der Home-Assistant-Integration für UniFi Network über die offizielle UniFi Network API
(Version 10.3.58, Authentifizierung per API-Schlüssel).

### Einrichtung
- Einrichtung im UI: Host, Port, API-Schlüssel, SSL-Prüfung; Auswahl des Standorts (ein Eintrag je Standort)
- Neu konfigurieren (Host, Port, API-Schlüssel, SSL) und erneute Anmeldung bei ungültigem API-Schlüssel
- Optionen: Abrufintervalle für Geräte/Clients und Gerätestatistik/-details, Clients verfolgen an/aus

### Entitäten
- **Standort:** verbundene Clients gesamt, kabelgebunden, WLAN, VPN und Gäste; Anzahl adoptierter Geräte
- **Pro Gerät:** Status, Firmware-Update verfügbar, CPU- und Speicherauslastung, Uplink-Raten,
  letzter Neustart, IP-Adresse, verbundene Clients, Uplink-Gerät, letzte Provisionierung,
  Firmware-Version, Systemlast, Knopf *Neu starten*
- **Pro Funkband** (Access Points): Kanal, Kanalbreite, WLAN-Standard, TX-Wiederholungen
- **Pro Port:** Verbindung, Geschwindigkeit, maximale Geschwindigkeit, Anschlusstyp; bei PoE-Ports
  PoE-Status, PoE-Details und Knopf *PoE neu starten*
- **Clients:** Device-Tracker für kabelgebundene und WLAN-Clients (standardmäßig deaktiviert)

### Sonstiges
- Gerätestatistik und Ports werden nach dem Start im Hintergrund geladen
- Letzter Neustart wird aus dem Heartbeat abgeleitet und über Neustarts von Home Assistant hinweg
  wiederhergestellt (keine Sprünge ohne echten Geräteneustart)
- Neu adoptierte Geräte erhalten ihre Entitäten ohne Neustart
- Eigenes Integrationslogo und Entitäts-Icons
- Diagnose-Export mit geschwärztem API-Schlüssel und Host
- Texte auf Deutsch und Englisch
- GitHub Actions: Tests (pytest, ruff) sowie hassfest- und HACS-Prüfung
- Kategorien im Manifest (`computers_network.routers_network`, `presence_location.network_presence`),
  damit die HACS-Prüfung nicht mehr warnt
