# UniFi Network Extended für Home Assistant

[![Tests](https://github.com/alexanderwendel8/Unifi-Network-Extended-HA/actions/workflows/tests.yml/badge.svg)](https://github.com/alexanderwendel8/Unifi-Network-Extended-HA/actions/workflows/tests.yml) [![Validate](https://github.com/alexanderwendel8/Unifi-Network-Extended-HA/actions/workflows/validate.yml/badge.svg)](https://github.com/alexanderwendel8/Unifi-Network-Extended-HA/actions/workflows/validate.yml)

Custom Integration für Home Assistant, die eine UniFi Network Anwendung
(z. B. auf einer UniFi-OS-Konsole wie UCG, UDM oder Cloud Key) über die
**offizielle UniFi Network API** anbindet – mit einem API-Schlüssel statt
Benutzername und Passwort und ohne inoffizielle Endpunkte. Die verwendete
Spezifikation liegt unter
[`docs/unifi-network-api.openapi.json`](docs/unifi-network-api.openapi.json)
(UniFi Network API 11.0.97).

**Was die Integration bietet:**
- **Gateways, Switches und Access Points** als Geräte mit Status, CPU- und
  Speicherauslastung, Uplink-Raten, letztem Neustart, Firmware-Update-Hinweis,
  verbundenen Clients, Uplink-Gerät (Netzwerk-Topologie) und Knopf *Neu starten*
- **Jeden Switch-Port** mit Verbindung und Geschwindigkeit, bei PoE-Ports mit
  PoE-Status und Knopf *PoE neu starten*
- **Jedes Funkband** der Access Points mit Kanal, Kanalbreite, WLAN-Standard und
  TX-Wiederholungen
- **Clients** als Anzahl pro Standort und Gerät sowie optional als Device-Tracker
  für die Anwesenheitserkennung

Einrichtung und Konfiguration erfolgen vollständig über die Oberfläche von
Home Assistant.

> **Status:** Version 0.2.0 – an einem echten UniFi-Netz getestet
> (siehe [Getestete Geräte](#getestete-geräte)).

## Getestete Geräte

Getestet an einem echten UniFi-Netz mit folgender Umgebung und folgenden Geräten:

| Umgebung | Version |
|---|---|
| Home Assistant | 2026.11.2 (Home Assistant OS 18.4) |
| UniFi Network Extended | 0.2.0 |
| UniFi Network API (Spezifikation) | 11.0.97 |
| UniFi-Network-Anwendung (Sensor *UniFi-Network-Version*) | 11.0.104 |

| Gerät | Typ | Firmware |
|---|---|---|
| UCG Max | Cloud Gateway (Konsole mit UniFi Network) | 6.0.17 |
| USW Pro Max 16 PoE | Switch, PoE | 7.5.15 |
| USW Flex 2.5G 8 PoE | Switch, PoE | 2.1.8 |
| USW Flex 2.5G 5 | Switch | 2.1.8 |
| UDB Switch | Device Bridge (Funk-Brücke mit Switch) | 8.8.14 |
| U7 Pro Max | Access Point, Wi-Fi 7 | 8.8.14 |
| U7 Pro | Access Point, Wi-Fi 7 | 8.8.14 |
| U7-Pro-Wall | Access Point, Wi-Fi 7 | 8.8.14 |
| U7 Mesh | Access Point, Wi-Fi 7 | 8.8.14 |

**Am echten Netz geprüft:** Einrichtung mit API-Schlüssel und Standort, alle
Sensoren und Binärsensoren für Standort, Geräte, Ports und Funkbänder, die
Uplink-Topologie, Clients pro Gerät, Start im Hintergrund (Einrichtung in rund
1,5 s), stabile Werte über Reloads und Neustarts von Home Assistant sowie
Installation und Updates über den Marketplace.

**Noch nicht am echten Netz geprüft** (nur mit automatischen Tests): die Knöpfe
*Neu starten* und *PoE neu starten*, Neu konfigurieren und erneute Anmeldung,
mehrere Standorte und selbst gehostete UniFi-Network-Server.

Weitere Rückmeldungen zu Geräten gern als
[Issue](https://github.com/alexanderwendel8/Unifi-Network-Extended-HA/issues).

## Installation

**Voraussetzung:** Home Assistant **2025.8.0** oder neuer (wie in
[`hacs.json`](hacs.json) angegeben). Die automatischen Tests laufen gegen diese
Mindestversion, gegen 2026.2 (letzte Version für Python 3.13) und gegen die
aktuelle Version.

Die Integration ist (noch) nicht im offiziellen Katalog enthalten und wird als
**benutzerdefiniertes Repository** hinzugefügt.

### Marketplace (ab Home Assistant 2026.11)

Seit Home Assistant 2026.11 ist HACS als **Marketplace** fest in Home Assistant
eingebaut; HACS muss nicht mehr separat installiert werden (und lässt sich ab
2026.11 auch nicht mehr installieren).

1. *Einstellungen → Marketplace* öffnen.
2. Oben rechts **Add from link** wählen.
3. Unter **GitHub link** `https://github.com/alexanderwendel8/Unifi-Network-Extended-HA`
   eintragen und **Add** wählen. Falls der Typ nicht erkannt wird, unter **Type**
   *Integration* auswählen und erneut **Add** wählen.
4. „UniFi Network Extended“ in der Liste öffnen, installieren und Home Assistant
   neu starten, wenn eine Reparaturmeldung dazu auffordert.

Zum Hinzufügen eines benutzerdefinierten Repositorys verlangt der Marketplace eine
Verbindung mit GitHub (nur Lesezugriff auf öffentliche Daten). Neue Versionen
werden dann alle 48 Stunden geprüft und unter *Einstellungen → Updates*
angeboten; nach einem Update startet man Home Assistant über die angezeigte
Reparaturmeldung neu. Standardmäßig werden nur stabile
[Releases](#releases) angeboten, keine Vorabversionen.

(Bezeichnungen laut der englischen Dokumentation der
[Marketplace-Integration](https://www.home-assistant.io/integrations/marketplace/);
in der deutschen Oberfläche können sie abweichen.)

### HACS (bis Home Assistant 2026.10)

1. HACS → Integrationen → ⋮ → *Benutzerdefinierte Repositories*
2. URL dieses Repositorys hinzufügen, Kategorie *Integration*
3. „UniFi Network Extended“ installieren und Home Assistant neu starten

Beim Update auf Home Assistant 2026.11 übernimmt der Marketplace die mit HACS
installierte Integration automatisch – samt benutzerdefiniertem Repository und
Update-Entität. Es ist nichts weiter zu tun.

### Manuell
Ordner `custom_components/unifi_network_extended` nach
`<config>/custom_components/` kopieren und Home Assistant neu starten.

## Einrichtung

*Einstellungen → Geräte & Dienste → Integration hinzufügen → „UniFi Network Extended“*

| Feld | Beschreibung |
|---|---|
| Host | Hostname, IPv4- oder IPv6-Adresse des Controllers, ohne `https://` (z. B. `192.168.1.1`, `unifi.local`, `fd00::1`). Ein eingefügtes `https://`, ein Pfad oder ein Port (`unifi.local:8443`, `[fd00::1]:8443`) werden automatisch bereinigt bzw. ins Feld Port übernommen |
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
- UniFi-Network-Version (Diagnose): Version der UniFi-Network-Anwendung, zugleich
  als Firmware-Version des Standort-Geräts angezeigt; wird stündlich geprüft
  (`GET /v1/info`)

**Pro UniFi-Gerät** (Gateway, Switch, Access Point …)
- Status (Online, Offline, Wird aktualisiert, …)
- Firmware-Update verfügbar (Binärsensor)
- CPU- und Speicherauslastung, Uplink Download- und Upload-Rate
- Letzter Neustart, IP-Adresse
- Verbundene Clients (direkt an diesem Switch bzw. Access Point)
- Uplink-Gerät (an welchem Gerät es hängt) und Zeitpunkt der letzten Provisionierung (Diagnose)
- Firmware-Version und Systemlast (standardmäßig deaktiviert)
- Knopf *Neu starten* (nur verfügbar, solange das Gerät online ist)

**Pro Funkband** (Access Points, je 2,4 / 5 / 6 GHz)
- Kanal, Kanalbreite und WLAN-Standard (Diagnose)
- Sendeleistung als Modus (Automatisch, Niedrig, Mittel, Hoch, Benutzerdefiniert, Deaktiviert;
  Diagnose, ab UniFi Network 11.0)
- TX-Wiederholungen in % (Anteil erneut gesendeter Pakete, ein Hinweis auf
  Störungen oder Überlast)

**Pro Port** (Switches, Gateways mit Switch-Ports)
- Verbindung (verbunden/getrennt)
- Aktuelle Geschwindigkeit (Diagnose)
- Maximale Geschwindigkeit und Anschlusstyp (RJ45, SFP, SFP+ …) (Diagnose, standardmäßig
  deaktiviert)
- Nur PoE-Ports: PoE-Status (Liefert Strom, Aus, Begrenzt; Diagnose) und Knopf
  *PoE neu starten* (Power-Cycle, z. B. für hängende Kameras oder Access Points);
  beide nur aktiviert, wo PoE eingeschaltet ist. PoE aktiviert, PoE-Standard und
  PoE-Typ als Diagnose (standardmäßig deaktiviert)

Auf der Geräteseite steht damit je Port nur die Verbindung unter „Sensoren“, alles Weitere
unter „Diagnose“.

PoE lässt sich über die offizielle API nicht dauerhaft ein- oder ausschalten, und
die Leistungsaufnahme wird nicht geliefert.

Statistik- und Portwerte gibt es nur für Geräte, die online sind.
Sie werden nach dem Start im Hintergrund geladen; bis dahin sind die
Statistik-Sensoren kurz nicht verfügbar und die Port-Entitäten erscheinen,
sobald ihre Daten da sind. Neu adoptierte Geräte
erhalten ihre Entitäten automatisch, ohne Neustart.

Geräte, die UniFi nicht mehr meldet (z. B. nach „Gerät vergessen“, Rückgabe oder
Austausch), werden nach dem nächsten erfolgreichen Abruf automatisch samt ihren
Entitäten aus Home Assistant entfernt, auch wenn das während eines Neustarts von
Home Assistant passiert ist. Offline-Geräte meldet UniFi weiterhin, sie bleiben
erhalten. Schlägt ein Abruf fehl, wird nichts entfernt. Ein solches Gerät lässt
sich außerdem auf seiner Geräteseite von Hand löschen; Geräte, die UniFi noch
meldet, und das Standort-Gerät nicht. Wird ein entferntes Gerät erneut adoptiert,
bekommt es wieder neue Entitäten.

**Clients** (Device-Tracker)
- Für jeden kabelgebundenen oder WLAN-Client mit MAC-Adresse: *zu Hause*, solange
  er verbunden ist. VPN-Verbindungen werden nicht verfolgt.
- Wie bei anderen Router-Integrationen legt Home Assistant die Tracker
  deaktiviert an (bis Version 2026.x nur, wenn noch kein Gerät mit derselben
  MAC-Adresse bekannt ist). Gewünschte Tracker lassen sich einzeln einschalten;
  sie werden dann dem Gerät mit dieser MAC-Adresse zugeordnet, z. B. dem
  Smartphone aus der Companion-App, sonst entsteht ein eigenes Gerät.
- Tracker von Clients, die **180 Tage** nicht verbunden waren, entfernt die
  Integration automatisch, auch eingeschaltete. Geprüft wird beim Start und
  danach einmal täglich. Ein Gerät, das nur für den Tracker angelegt wurde,
  verschwindet mit; Geräte anderer Integrationen (z. B. das Smartphone aus der
  Companion-App) bleiben erhalten. So wächst das Entitätenregister nicht durch
  Gäste oder wechselnde private WLAN-Adressen von Smartphones.
- Die API liefert nur verbundene Clients. Den Zeitpunkt der letzten Verbindung
  speichert die Integration daher selbst (in `.storage/`, wird beim Entfernen
  der Integration gelöscht). Für Tracker, die vor dem Update schon da waren,
  beginnt die Frist mit dem ersten Start.
- Taucht der Client später wieder auf, entsteht wieder ein Tracker. Er ist wie
  gewohnt deaktiviert, bis man ihn einschaltet. Ausnahme: Home Assistant merkt
  sich die Einstellungen entfernter Entitäten (Entitäts-ID, Name, Bereich,
  ein-/ausgeschaltet) und stellt sie wieder her; ein vorher eingeschalteter
  Tracker kommt also eingeschaltet und mit derselben Entitäts-ID zurück
  (Quelle: [`entity_registry.py`](https://github.com/home-assistant/core/blob/2026.11.2/homeassistant/helpers/entity_registry.py),
  `async_get_or_create`).
- **Hinweis für Automationen:** Zwischen dem Entfernen und dem Wiederauftauchen
  gibt es die Entität nicht. Automationen und Skripte, die einen solchen
  Tracker verwenden, lösen dann nicht aus bzw. ihre Bedingungen sind nicht
  erfüllt. Für Anwesenheitserkennung eignen sich deshalb nur Geräte, die
  regelmäßig verbunden sind und eine feste MAC-Adresse verwenden (bei
  Smartphones die private WLAN-Adresse für das Heimnetz ausschalten).

## Symbole

Das Integrationslogo liegt unter `custom_components/unifi_network_extended/brand/`
und wird ab Home Assistant 2026.3 für die Integration und ihre Geräte angezeigt
(ältere Versionen zeigen einen Platzhalter). Es ist ein eigenes Motiv und nicht
das UniFi-Logo von Ubiquiti. Die Entitäts-Icons sind in `icons.json` hinterlegt.

## Aktualisierung und Optionen

Die offizielle UniFi Network API bietet keine Push-Benachrichtigungen
(kein WebSocket, keine Webhooks). Die Integration fragt die Daten daher
regelmäßig ab. Unter *⋮ → Optionen* einstellbar:

| Option | Standard | Hinweis |
|---|---|---|
| Abrufintervall Geräte und Clients | 30 s | min. 10 s |
| Abrufintervall Gerätestatistik und Gerätedetails | 60 s | min. 30 s; je zwei Anfragen pro Gerät (Statistik, Details mit Ports und Uplink) |
| Clients verfolgen | an | Tracker von Clients, die 180 Tage nicht verbunden waren, werden automatisch entfernt (auch eingeschaltete; kommt der Client wieder, entsteht ein neuer Tracker); beim Ausschalten werden alle Tracker und die gespeicherten Verbindungszeiten entfernt |

Die Version der UniFi-Network-Anwendung wird unabhängig davon beim Start und
danach stündlich abgefragt. Schlägt die Abfrage fehl, startet die Integration
trotzdem; der Sensor ist dann bis zur nächsten erfolgreichen Abfrage nicht
verfügbar, die am Standort-Gerät gespeicherte Version bleibt erhalten.

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

Bei jedem Push und Pull Request laufen auf GitHub automatisch:
- **Tests:** `pytest` mit Python 3.13 und 3.14 (ältere und aktuelle
  Home-Assistant-Versionen) sowie `ruff` (Lint und Formatierung)
- **Validate:** `hassfest` (Prüfung durch Home Assistant) und die HACS-Prüfung

Die verwendeten GitHub Actions sind auf einen Commit-SHA mit der Version als Kommentar
festgelegt. [Dependabot](.github/dependabot.yml) prüft wöchentlich auf neue Versionen und
schlägt Updates als Pull Request vor.

Zusätzlich prüft der Workflow [`update-check.yml`](.github/workflows/update-check.yml)
jeden Montag alle externen Komponenten und legt für jede veraltete Komponente ein Issue mit
dem Label `aktualisierung` an:
- **GitHub Actions** in `.github/workflows` (neues Release)
- **Python-Pakete**, die in `requirements_test.txt` oder den Workflows fest gepinnt sind
  (zum Beispiel `ruff`, `pytest-homeassistant-custom-component`)
- **Home Assistant:** neues Monatsrelease gegenüber der im README getesteten Version und
  eine höhere Python-Mindestversion als in der Test-Matrix

- **UniFi Network API:** neuere gespiegelte Version als die, gegen die entwickelt wird

Ist die Komponente wieder aktuell, schließt der Workflow das Issue selbst. Die Prüfungen stehen
in [`.github/scripts/check_updates.py`](.github/scripts/check_updates.py); lokal zeigt
`python .github/scripts/check_updates.py --dry-run` das Ergebnis, ohne Issues zu ändern.

Der Workflow [`api-mirror.yml`](.github/workflows/api-mirror.yml) spiegelt jeden Montag die
offiziellen Spezifikationen der UniFi Network API von <https://developer.ui.com/network> nach
[`docs/api/`](docs/api/README.md), eine Datei je Version. Vorhandene Versionen werden nie
geändert oder gelöscht. Neue Dateien committet der Workflow direkt auf `main`.

Neue Funktionen werden ausschließlich gegen die offizielle API aus
`docs/unifi-network-api.openapi.json` entwickelt (siehe `CLAUDE.md`).

```bash
pip install -r requirements_test.txt
pytest
```

### Testabdeckung

Die Abdeckung (Zeilen und Zweige) misst `pytest-cov`, das mit
`pytest-homeassistant-custom-component` installiert wird. Die Einstellungen stehen in
`pyproject.toml` (`[tool.coverage.*]`), der Aufruf folgt der
[Entwickler-Doku von Home Assistant](https://github.com/home-assistant/developers.home-assistant/blob/master/docs/development_testing.md):

```bash
pytest --cov --cov-report=term-missing
```

`Missing` nennt die nicht ausgeführten Zeilen und Zweige. Mit `--cov-report=html` entsteht
zusätzlich ein Bericht in `htmlcov/`. Die CI zeigt die Abdeckung im Log und in der
Zusammenfassung des Actions-Laufs und schlägt fehl, wenn sie unter 97 % fällt
(`--cov-fail-under=97` in `.github/workflows/tests.yml`).

## Releases

Änderungen stehen in [`CHANGELOG.md`](CHANGELOG.md); was noch in keinem Release ist, steht dort
unter „Unreleased“. Releases erstellt der Workflow `release.yml`
mit den Notizen aus dem Changelog – entweder per Tag `vX.Y.Z` oder manuell unter
*Actions → Release → Run workflow* (auf `main`, Eingabe z. B. `0.1.0`; der Tag wird dann gesetzt).
Die Version muss zu `manifest.json` passen. Marketplace bzw. HACS zeigen dann die Versionsnummer
statt des Commit-Hashs und bieten neue Releases als Update an.

### Vorabversionen

Der Marketplace meldet nur Releases als Update, keine einzelnen Commits auf `main`
([Quellcode](https://github.com/home-assistant/core/blob/2026.11.2/homeassistant/components/marketplace/repositories/base.py)).
Zum Testen vor einem Release erstellt der Workflow `prerelease.yml` eine Vorabversion vom
aktuellen Stand von `main`: *Actions → Pre-release → Run workflow*, Eingabe ist die geplante
nächste Version, z. B. `0.4.0`. Daraus entsteht `v0.4.0b1`, beim nächsten Lauf `v0.4.0b2` usw.,
mit den Notizen aus „Unreleased“. Ein Pull Request ist dafür nicht nötig; `main` bleibt
unverändert (die Version `0.4.0b1` steht nur im Commit des Tags).

Der Marketplace bietet Vorabversionen nur an, wenn beim Repository der Schalter **Pre-release**
eingeschaltet ist: *Einstellungen → Geräte & Dienste → Marketplace → UniFi Network Extended*,
dort die standardmäßig deaktivierte Entität **Pre-release** aktivieren und einschalten
([Doku](https://www.home-assistant.io/integrations/marketplace)). Alle anderen bekommen weiter
nur stabile Releases.
