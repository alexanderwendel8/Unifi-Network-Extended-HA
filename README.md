# UniFi Network Extended für Home Assistant

Custom Integration für Home Assistant, die eine UniFi Network Anwendung
(z. B. UniFi-OS-Konsole wie UDM/UCG/Cloud Key) über die **offizielle
UniFi Network API** anbindet. Die verwendete Spezifikation liegt unter
[`docs/unifi-network-api.openapi.json`](docs/unifi-network-api.openapi.json).

> Status: Grundgerüst – Einrichtung und Prüfung des API-Schlüssels sind implementiert, Entitäten folgen.

## Installation

### HACS (benutzerdefiniertes Repository)
1. HACS → Integrationen → ⋮ → *Benutzerdefinierte Repositories*
2. URL dieses Repositories hinzufügen, Kategorie *Integration*
3. „UniFi Network Extended“ installieren und Home Assistant neu starten

### Manuell
Ordner `custom_components/unifi_network_extended` nach
`<config>/custom_components/` kopieren und Home Assistant neu starten.

## Einrichtung

*Einstellungen → Geräte & Dienste → Integration hinzufügen → „UniFi Network Extended“*

| Feld | Beschreibung |
|---|---|
| Host | Hostname oder IP-Adresse des Controllers |
| Port | meist `443` |
| API-Schlüssel | Wird im Bereich *Integrationen* der UniFi Network Anwendung erzeugt |
| SSL-Zertifikat prüfen | Nur bei selbstsignierten Zertifikaten deaktivieren |

Danach werden die Standorte (Sites) über `GET /v1/sites` abgerufen – das prüft
zugleich den API-Schlüssel. Gibt es nur einen Standort, wird er automatisch
übernommen, sonst wählst du ihn aus einer Liste. Pro Standort entsteht ein eigener
Eintrag; für weitere Standorte die Integration einfach erneut hinzufügen
(bereits eingerichtete Standorte werden nicht mehr angeboten).

Beim Start prüft die Integration, ob der Standort noch existiert.
Host, Port, API-Schlüssel und SSL-Option lassen sich später über
*⋮ → Neu konfigurieren* ändern (der Standort bleibt dabei fest). Wird der API-Schlüssel ungültig, fordert
Home Assistant automatisch einen neuen an.

## Speicherung des API-Schlüssels

Die Daten werden – wie bei allen Core-Integrationen – im Config Entry von
Home Assistant gespeichert (`<config>/.storage/core.config_entries`), nicht in
der `configuration.yaml`. Zusätzlich gilt:

- Der API-Schlüssel wird im UI als verdecktes Feld angezeigt und nie vorausgefüllt.
- API-Schlüssel und Host werden in Diagnosedaten geschwärzt und nicht geloggt.
- SSL-Prüfung ist standardmäßig aktiviert.
- Es wird kein Benutzerpasswort gespeichert; der API-Schlüssel kann in UniFi
  jederzeit widerrufen werden.

Schütze das `.storage`-Verzeichnis und deine Backups entsprechend
(Backups von Home Assistant lassen sich verschlüsseln).

## Entwicklung

Neue Funktionen werden ausschließlich gegen die offizielle API aus
`docs/unifi-network-api.openapi.json` entwickelt (siehe `CLAUDE.md`).

```bash
pip install -r requirements_test.txt
pytest
```
