# Changelog

## Unreleased

### Neu
- **Standort:** Diagnose-Sensor *UniFi-Network-Version* mit der Version der
  UniFi-Network-Anwendung (`GET /v1/info`); dieselbe Version steht als Firmware-Version am
  Standort-Gerät und in den Diagnosedaten. Abfrage beim Start und danach stündlich; ein Fehler
  dabei verhindert den Start nicht, ein ungültiger API-Schlüssel startet die erneute Anmeldung.

### Sonstiges
- Mindestversion Home Assistant 2025.3.0 (wie bisher in `hacs.json`) geprüft und in der README genannt;
  die CI testet jetzt 2025.3.0, 2026.2.3 und die aktuelle Version mit festgelegten Versionen von
  `pytest-homeassistant-custom-component` (aktuelle Version per Dependabot aktualisiert)

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
