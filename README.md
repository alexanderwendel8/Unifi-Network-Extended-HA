# UniFi Network Extended für Home Assistant

Custom Integration für Home Assistant, die eine UniFi Network Anwendung
(z. B. UniFi-OS-Konsole wie UDM/UCG/Cloud Key) über die **offizielle
UniFi Network API** anbindet. Die verwendete Spezifikation liegt unter
[`docs/unifi-network-api.openapi.json`](docs/unifi-network-api.openapi.json).

> Status: frühe Entwicklung – Einrichtung, Geräte- und Client-Entitäten sind umgesetzt.

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

## Entitäten

**Standort** (ein Gerät pro Standort)
- Verbundene Clients gesamt, kabelgebunden und WLAN
- VPN- und Gast-Clients (standardmäßig deaktiviert)
- Anzahl adoptierter Geräte

**Pro UniFi-Gerät** (Gateway, Switch, Access Point …)
- Status (Online, Offline, Wird aktualisiert, …)
- Firmware-Update verfügbar (Binärsensor)
- CPU- und Speicherauslastung, Uplink Download- und Upload-Rate
- Letzter Neustart, IP-Adresse
- Firmware-Version und Systemlast (standardmäßig deaktiviert)
- Knopf *Neu starten* (nur verfügbar, solange das Gerät online ist)

Statistikwerte gibt es nur für Geräte, die online sind. Neu adoptierte Geräte
erhalten ihre Entitäten automatisch, ohne Neustart.

**Clients** (Device-Tracker)
- Für jeden kabelgebundenen oder WLAN-Client mit MAC-Adresse: *zu Hause*, solange
  er verbunden ist. VPN-Verbindungen werden nicht verfolgt.
- Wie bei anderen Router-Integrationen legt Home Assistant Tracker nur dann
  aktiviert an, wenn ein Gerät mit derselben MAC-Adresse bereits bekannt ist.
  Alle anderen Tracker sind vorhanden, aber deaktiviert und lassen sich einzeln
  einschalten.

## Aktualisierung und Optionen

Die offizielle UniFi Network API bietet keine Push-Benachrichtigungen
(kein WebSocket, keine Webhooks). Die Integration fragt die Daten daher
regelmäßig ab. Unter *⋮ → Optionen* einstellbar:

| Option | Standard | Hinweis |
|---|---|---|
| Abrufintervall Geräte und Clients | 30 s | min. 10 s |
| Abrufintervall Gerätestatistik | 60 s | min. 30 s; eine Anfrage pro Gerät |
| Clients verfolgen | an | beim Ausschalten werden die Tracker entfernt |

## Speicherung des API-Schlüssels

Die Daten werden – wie bei allen Core-Integrationen – im Config Entry von
Home Assistant gespeichert (`<config>/.storage/core.config_entries`), nicht in
der `configuration.yaml`. Zusätzlich gilt:

- Der API-Schlüssel wird im UI als verdecktes Feld angezeigt und nie vorausgefüllt.
- API-Schlüssel und Host werden in Diagnosedaten geschwärzt und nicht geloggt.
  Diagnosedaten enthalten keine Client-Namen oder -Adressen.
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
