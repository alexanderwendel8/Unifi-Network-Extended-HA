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
- Tests: `pytest` (siehe `requirements_test.txt`).
- Releases: Ablauf und wiederverwendbare Vorlage in `.claude/skills/release/SKILL.md`
  (Version in `manifest.json` + Abschnitt in `CHANGELOG.md`, dann Workflow `release.yml` manuell auf `main` starten).
