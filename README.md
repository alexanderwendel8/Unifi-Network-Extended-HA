# UniFi Network Extended für Home Assistant

Custom Integration für Home Assistant, die einen UniFi Network Controller
(UniFi-OS-Konsole wie UDM/UCG/Cloud Key oder selbst gehosteter Controller) anbindet.

> Status: Grundgerüst – Einrichtung und Anmeldung sind implementiert, Entitäten folgen.

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
| Port | `443` (UniFi OS) bzw. `8443` (selbst gehosteter Controller) |
| Benutzername / Passwort | Empfohlen: eigener **lokaler** UniFi-Benutzer mit minimal nötigen Rechten |
| SSL-Zertifikat prüfen | Nur bei selbstsignierten Zertifikaten deaktivieren |

Die Zugangsdaten werden beim Einrichten durch einen Login-Versuch geprüft.
Host, Port, Zugangsdaten und SSL-Option lassen sich später über
*⋮ → Neu konfigurieren* ändern. Werden die Zugangsdaten ungültig, fordert
Home Assistant automatisch zur erneuten Anmeldung auf.

## Speicherung der Zugangsdaten

Die Daten werden – wie bei allen Core-Integrationen – im Config Entry von
Home Assistant gespeichert (`<config>/.storage/core.config_entries`), nicht in
der `configuration.yaml`. Zusätzlich gilt:

- Das Passwort wird im UI als Passwortfeld angezeigt und nie vorausgefüllt.
- Passwort, Benutzername und Host werden in Diagnosedaten geschwärzt und nicht geloggt.
- Die Integration nutzt eine eigene HTTP-Session, damit das Login-Cookie nicht
  mit anderen Integrationen geteilt wird.
- SSL-Prüfung ist standardmäßig aktiviert.

Schütze das `.storage`-Verzeichnis und deine Backups entsprechend
(Backups von Home Assistant lassen sich verschlüsseln).

## Entwicklung

```bash
pip install -r requirements_test.txt
pytest
```
