# Entwicklungsregeln

- UniFi-Funktionen werden **ausschließlich** gegen die offizielle UniFi Network API
  entwickelt. Maßgeblich ist `docs/unifi-network-api.openapi.json`
  (UniFi Network API, Version 10.3.58).
- Keine inoffiziellen oder undokumentierten Endpunkte verwenden, zum Beispiel
  `/api/auth/login`, `/api/s/<site>/...` oder `/proxy/network/api/...`.
  Ist eine Funktion in der Spezifikation nicht vorhanden, wird sie nicht umgesetzt.
- Basis-URL lokal: `https://{host}:{port}/proxy/network/integration`,
  Authentifizierung per Header `X-API-KEY`.
- Alle HTTP-Aufrufe laufen über `custom_components/unifi_network_extended/api.py`.
  Jede Client-Methode nennt im Docstring den Endpunkt aus der Spezifikation.
- Listen-Endpunkte sind paginiert (`offset`/`limit`, max. 200); `_get_all_pages` verwenden.
- API-Key, Host und andere Geheimnisse nie loggen; in Diagnosedaten schwärzen.
- Tests: `pytest` (siehe `requirements_test.txt`). Die CI (`.github/workflows/tests.yml`)
  testet die Mindestversion aus `hacs.json` (2025.8.0), 2026.2.3 (letzte Version für
  Python 3.13) und die aktuelle Version; die Mindestversion in `hacs.json`, README und
  Workflow gemeinsam ändern.
- Jede Änderung (Code, Doku, Workflows) bekommt einen Eintrag unter `## Unreleased` in
  `CHANGELOG.md`, auf Deutsch und in der passenden Unterrubrik. Gibt es den Abschnitt nicht,
  wird er direkt unter der Einleitung angelegt.
- Releases: Ablauf und wiederverwendbare Vorlage in `.claude/skills/release/SKILL.md`
  (Version in `manifest.json` + Abschnitt in `CHANGELOG.md`, dann Workflow `release.yml` manuell auf `main` starten).

# Aktualisierungs-Issues

- Der Workflow `.github/workflows/update-check.yml` (Logik: `.github/scripts/check_updates.py`)
  legt wöchentlich für jede veraltete externe Komponente ein Issue mit dem Label
  `aktualisierung` an und schließt es, sobald die Komponente aktuell ist.
- Zu Beginn jeder Sitzung, vor der ersten Aufgabe, die offenen Issues mit dem Label
  `aktualisierung` über die GitHub-Tools abrufen und jedes prüfen:
  - Ist es noch zutreffend (Version im Repository mit dem Issue vergleichen)?
  - Gibt es dafür schon einen offenen Pull Request (z. B. von Dependabot)?
  - Was ist zu tun und wie riskant ist es (Release Notes bzw. Changelog der Komponente
    auf Breaking Changes und neue Anforderungen lesen)?
- Das Ergebnis kurz zusammenfassen und den Nutzer fragen, ob und welche Issues abgearbeitet
  werden sollen. **Ohne Zustimmung nichts ändern.** Gibt es keine offenen Issues, das nur
  in einem Satz erwähnen.
- Beim Abarbeiten gelten die übrigen Regeln (CHANGELOG-Eintrag, Tests, CI-Matrix); im Pull
  Request das Issue mit `Closes #<Nummer>` verknüpfen.

# Quellen zu Home Assistant

- Fragen zu Home Assistant (Verhalten, Menüs, Funktionen, Integrationen wie der
  Marketplace) werden mit der **offiziellen Home-Assistant-Dokumentation** beantwortet,
  nicht aus dem Gedächtnis und nicht aus Blogs oder Foren.
- Die gesamte Doku liegt als Markdown im Repo `home-assistant/home-assistant.io`.
  Diese Markdown-Dateien statt der HTML-Seiten lesen, z. B. per `curl`:
  - Integrationen: `source/_integrations/<domain>.markdown`
    (z. B. `.../current/source/_integrations/marketplace.markdown`)
  - Allgemeine Doku: `source/_docs/`
  - Basis-URL: `https://raw.githubusercontent.com/home-assistant/home-assistant.io/current/`
    (`current` = veröffentlichte Version, `next` = kommende Version)
- Ergänzend für die Entwicklung der Integration: Entwickler-Doku im Repo
  `home-assistant/developers.home-assistant` (`docs/`, `blog/`) und der Quellcode von
  `home-assistant/core` zum passenden Release-Tag (z. B. `.../core/2026.11.2/homeassistant/...`).
- Gelesene Doku in Antworten, README und Pull Requests als Quelle nennen (Link zur
  Seite auf home-assistant.io bzw. zur Datei im Repo).
