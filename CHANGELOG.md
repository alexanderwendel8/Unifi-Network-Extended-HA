# Changelog

## Unreleased

### Einrichtung
- Host als Hostname, IPv4- oder IPv6-Adresse; IPv6-Adressen werden in der URL korrekt in
  eckige Klammern gesetzt (z. B. `https://[fd00::1]:443/...`)
- Eingabe des Hosts wird bereinigt (Einrichten und Neu konfigurieren): Leerzeichen, `http://`/`https://`,
  abschließender `/` bzw. Pfad und eckige Klammern um IPv6-Adressen werden entfernt
- Ein Port in der Host-Eingabe (`unifi.local:8443`, `[fd00::1]:8443`) wird ins Feld Port übernommen
- Ungültige Hosts werden mit dem Fehler „Ungültiger Host“ abgelehnt, statt eine Verbindung zu versuchen
- Beim Neu konfigurieren bleiben die Eingaben nach einem Fehler im Formular erhalten

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
