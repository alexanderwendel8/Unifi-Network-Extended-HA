---
name: release
description: GitHub-Release für ein Projekt anlegen oder den Release-Prozess (CHANGELOG + Workflow mit Tag-Push und manuellem Start) in einem neuen Projekt einrichten. Verwenden bei "erstelle das Release", "Release X.Y.Z", "richte Releases ein", "HACS zeigt Commit-Hash statt Version".
---

# Release-Prozess

Ein Release besteht aus **Version in der Manifest-Datei**, **Abschnitt in `CHANGELOG.md`**,
**Tag `vX.Y.Z`** und **GitHub-Release mit den Notizen aus dem Changelog**. Tag und Release legt
ein GitHub-Actions-Workflow an – entweder per Tag-Push oder per manuellem Start
(`workflow_dispatch`). Der manuelle Start ist der Normalfall für Claude, weil Tag-Pushes aus der
Cloud-Umgebung abgelehnt werden (HTTP 403 vom Git-Proxy) und es kein MCP-Tool zum Anlegen von
Tags/Releases gibt.

## A. Einmalig einrichten (neues Projekt)

1. **Version festlegen** – Manifest-Datei des Projekts finden (`manifest.json` bei HA-Integrationen,
   `pyproject.toml`, `package.json` …). Den Nutzer nach der Versionsnummer fragen, wenn unklar
   (Vorschlag: `0.1.0` für das erste Release). SemVer `X.Y.Z`, Tag mit `v`-Präfix.
2. **`CHANGELOG.md`** anlegen. Je Version ein Abschnitt mit exakt dieser Überschrift (ohne `v`):
   ```markdown
   # Changelog

   ## 0.1.0

   Kurzbeschreibung …

   ### Geräte / Funktionen / Behoben …
   - …
   ```
   Der Workflow schneidet alles zwischen `## X.Y.Z` und der nächsten `## `-Zeile aus. Inhalte aus
   der Git-Historie und den gemergten PRs zusammenfassen, in der Projektsprache; ehrlich angeben,
   was nicht getestet ist.
3. **`.github/workflows/release.yml`** anlegen (Vorlage unten). Nur `MANIFEST_VERSION_CMD`
   anpassen, falls die Version nicht in einer `manifest.json` steht.
4. **README**: kurzer Abschnitt „Releases“ (wie man ein Release startet, Version muss passen).
5. Commit auf dem Arbeitsbranch, Push, **PR nur wenn der Nutzer es will**. Erst nach dem Merge in
   `main` kann der Workflow manuell gestartet werden (`workflow_dispatch` muss auf dem
   Default-Branch existieren).

### Vorlage `release.yml`

```yaml
name: Release

# Erstellt ein GitHub-Release mit den Notizen aus CHANGELOG.md, entweder
# - beim Push eines Tags vX.Y.Z oder
# - manuell (workflow_dispatch) auf main mit der Version als Eingabe; dann wird
#   der Tag vX.Y.Z auf den aktuellen Commit von main gesetzt.
# In beiden Fällen muss die Version zur Manifest-Datei passen.
on:
  push:
    tags:
      - "v*"
  workflow_dispatch:
    inputs:
      version:
        description: "Version ohne v, z. B. 0.1.0 (muss zur Manifest-Datei passen)"
        required: true

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Version prüfen und Release Notes extrahieren
        id: meta
        env:
          INPUT_VERSION: ${{ inputs.version }}
        run: |
          if [ "$GITHUB_EVENT_NAME" = "workflow_dispatch" ]; then
            if [ "$GITHUB_REF" != "refs/heads/main" ]; then
              echo "::error::Manuelle Releases nur von main (aktuell $GITHUB_REF)"
              exit 1
            fi
            version="${INPUT_VERSION#v}"
          else
            version="${GITHUB_REF_NAME#v}"
          fi
          if ! echo "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
            echo "::error::Ungültige Version '$version' (erwartet X.Y.Z)"
            exit 1
          fi
          # MANIFEST_VERSION_CMD – je Projekt anpassen:
          manifest=$(python3 -c "import json,glob; print(json.load(open(glob.glob('custom_components/*/manifest.json')[0]))['version'])")
          if [ "$version" != "$manifest" ]; then
            echo "::error::Version $version passt nicht zur Manifest-Datei ($manifest)"
            exit 1
          fi
          awk -v v="$version" '
            $0 ~ "^## " v "$" {found=1; next}
            found && /^## / {exit}
            found {print}
          ' CHANGELOG.md > release_notes.md
          if [ ! -s release_notes.md ]; then
            echo "::error::Kein Abschnitt '## $version' in CHANGELOG.md"
            exit 1
          fi
          echo "tag=v$version" >> "$GITHUB_OUTPUT"

      - uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ steps.meta.outputs.tag }}
          target_commitish: ${{ github.sha }}
          name: ${{ steps.meta.outputs.tag }}
          body_path: release_notes.md
```

Alternativen für `MANIFEST_VERSION_CMD`:
- `pyproject.toml`: `python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"`
- `package.json`: `node -p "require('./package.json').version"`

Prüfen vor dem Commit: `python3 -c "import yaml; print(list(yaml.safe_load(open('.github/workflows/release.yml'))[True]))"`
→ `['push', 'workflow_dispatch']` (PyYAML liest `on:` als `True`).

## B. Release erstellen (laufender Betrieb)

1. Version mit dem Nutzer klären (AskUserQuestion, Empfehlung zuerst).
2. Auf dem Arbeitsbranch: Version in der Manifest-Datei setzen, Abschnitt `## X.Y.Z` in
   `CHANGELOG.md` ergänzen, Tests/Lint laufen lassen, committen, pushen.
3. PR erstellen (wenn der Nutzer zustimmt), mit `subscribe_pr_activity` beobachten, CI grün halten.
   **Nicht selbst mergen** – der Nutzer merged.
4. Nach dem Merge den Workflow starten:
   ```
   mcp__github__actions_run_trigger(method="run_workflow", owner=…, repo=…,
       workflow_id="release.yml", ref="main", inputs={"version": "X.Y.Z"})
   ```
5. Ergebnis prüfen: `actions_list(method="list_workflow_runs", resource_id="release.yml")` bis
   `conclusion: success`, dann `get_latest_release` → `tag_name`, `body` kontrollieren.
   Bei Fehlschlag `get_job_logs` lesen; typische Ursachen: Version ≠ Manifest, fehlender
   Changelog-Abschnitt, Start nicht auf `main`.
6. Dem Nutzer den Link `https://github.com/<owner>/<repo>/releases/tag/vX.Y.Z` geben.

## Stolpersteine

- **Tag-Push** (`git push origin vX.Y.Z`) scheitert in der Cloud-Umgebung mit 403 → nicht
  erneut versuchen, lokalen Tag löschen (`git tag -d`), Weg über `workflow_dispatch` nehmen.
- `workflow_dispatch` ist erst startbar, wenn die Workflow-Datei auf dem Default-Branch liegt.
- Bereits existierender Tag/Release: softprops aktualisiert das Release, verschiebt den Tag aber
  nicht – für eine neue Version immer die Version erhöhen statt denselben Tag neu zu bauen.
- **HACS** (HA-Integrationen) zeigt ohne Releases den Commit-Hash. Nach dem ersten Release in HACS
  beim Repository „Informationen aktualisieren“ wählen, dann wird die Version als Update angeboten.
  HACS-Validierung braucht außerdem Repo-Beschreibung und Topics (setzt der Nutzer in den
  GitHub-Einstellungen) sowie ein Brand-Icon.
- Keine Modellbezeichnungen in Commits, PRs oder Release Notes.
