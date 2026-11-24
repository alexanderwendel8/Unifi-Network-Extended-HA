#!/usr/bin/env python3
"""Mirror the official UniFi Network API specifications into the repository.

Source is the official documentation at https://developer.ui.com:

1. ``sitemap.xml`` lists the documentation pages; their paths contain the
   published API versions (``/network/v11.0.97/...``).
2. For every version that is not mirrored yet, the OpenAPI document is
   downloaded: first ``/network/<version>/openapi.json``; if that is not
   served, it is taken from the page data of a documentation page (the
   ``fullSpec`` object the site embeds for its own rendering).
3. The document is stored unchanged in content as
   ``docs/api/network/<version>/openapi.json`` and ``docs/api/README.md``
   is regenerated.

Mirrored versions are never changed or deleted: a version that is already in
the repository is skipped, also when the source no longer lists it. The file
the integration is developed against (``docs/unifi-network-api.openapi.json``)
is not touched; adopting a newer version is a separate, deliberate change.

Usage: ``mirror_api.py [--dry-run]``. Only the standard library is used.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
from pathlib import Path
import re
import sys
from typing import Any
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://developer.ui.com"
APP = "network"
MIRROR_DIR = Path("docs") / "api" / APP
INDEX = Path("docs") / "api" / "README.md"
USER_AGENT = "unifi-network-extended-api-mirror"
# Pages tried per version when openapi.json is not served directly.
MAX_PAGES = 5

LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
VERSION_RE = re.compile(r"v\d+(?:\.\d+)+")
HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options")

# get(url, rsc) -> response text; rsc=True asks for the page data.
Fetch = Callable[[str, bool], str]


class MirrorError(Exception):
    """Raised when the source cannot be read as expected."""


def http_get(url: str, rsc: bool = False) -> str:
    """GET a text document from the official source."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if rsc:
        headers["RSC"] = "1"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def version_key(version: str) -> tuple[int, ...]:
    """Sort key for ``v11.0.97``."""
    return tuple(int(part) for part in re.findall(r"\d+", version))


def discover(get: Fetch) -> dict[str, list[str]]:
    """Return {version: [page URLs]} of the app from the sitemap."""
    locations = LOC_RE.findall(get(f"{ORIGIN}/sitemap.xml", False))
    # A sitemap index points to further sitemaps (one level).
    for nested in [loc for loc in locations if loc.endswith(".xml")]:
        locations += LOC_RE.findall(get(nested, False))

    versions: dict[str, list[str]] = {}
    for loc in locations:
        if not loc.startswith(f"{ORIGIN}/{APP}/"):
            continue
        version = loc.removeprefix(f"{ORIGIN}/{APP}/").split("/")[0]
        if VERSION_RE.fullmatch(version):
            versions.setdefault(version, []).append(loc)
    if not versions:
        raise MirrorError(f"sitemap.xml: keine Versionen für '{APP}' gefunden")
    return versions


def _is_spec(data: Any) -> bool:
    return isinstance(data, dict) and "openapi" in data and "paths" in data


def _spec_from_page(text: str) -> dict[str, Any] | None:
    """Extract the embedded ``fullSpec`` object from page data."""
    marker = text.find('"fullSpec":')
    start = text.find("{", marker) if marker >= 0 else -1
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(text, start)
    except ValueError:
        return None
    return data if _is_spec(data) else None


def fetch_spec(version: str, pages: list[str], get: Fetch) -> dict[str, Any]:
    """Download the OpenAPI document of one version."""
    spec: dict[str, Any] | None = None
    try:
        data = json.loads(get(f"{ORIGIN}/{APP}/{version}/openapi.json", False))
        if _is_spec(data):
            spec = data
    except (OSError, ValueError):
        pass

    if spec is None:
        for page in sorted(pages, key=len)[:MAX_PAGES]:
            try:
                spec = _spec_from_page(get(page, True))
            except OSError:
                continue
            if spec is not None:
                break
    if spec is None:
        raise MirrorError(f"{version}: keine OpenAPI-Spezifikation gefunden")

    declared = str(spec.get("info", {}).get("version", ""))
    if declared != version.removeprefix("v"):
        raise MirrorError(
            f"{version}: Spezifikation nennt Version {declared!r}, nicht gespeichert"
        )
    return spec


def mirrored_versions(root: Path) -> list[str]:
    """Versions already in the repository, newest first."""
    base = root / MIRROR_DIR
    versions = [
        path.parent.name
        for path in base.glob("v*/openapi.json")
        if VERSION_RE.fullmatch(path.parent.name)
    ]
    return sorted(versions, key=version_key, reverse=True)


def build_index(root: Path) -> str:
    """Overview of all mirrored versions (generated from the files)."""
    lines = [
        "# Gespiegelte UniFi-API-Spezifikationen",
        "",
        "Automatisch gespiegelt von der offiziellen Dokumentation",
        f"<{ORIGIN}/{APP}> durch den Workflow `api-mirror.yml`",
        "(`.github/scripts/mirror_api.py`). Die Dateien werden nicht von Hand",
        "bearbeitet; vorhandene Versionen werden nie geändert oder gelöscht.",
        "",
        "Entwickelt wird die Integration gegen",
        "[`docs/unifi-network-api.openapi.json`](../unifi-network-api.openapi.json);",
        "diese Datei wird nur bewusst auf eine neuere Version umgestellt.",
        "",
        "## UniFi Network API",
        "",
        "| Version | Pfade | Operationen | Datei |",
        "|---|---|---|---|",
    ]
    for version in mirrored_versions(root):
        spec = json.loads(
            (root / MIRROR_DIR / version / "openapi.json").read_text(encoding="utf-8")
        )
        paths = spec.get("paths", {})
        operations = sum(
            1
            for item in paths.values()
            if isinstance(item, dict)
            for method in item
            if method in HTTP_METHODS
        )
        lines.append(
            f"| {version.removeprefix('v')} | {len(paths)} | {operations} "
            f"| [`{APP}/{version}/openapi.json`]({APP}/{version}/openapi.json) |"
        )
    return "\n".join(lines) + "\n"


def mirror(
    root: Path, get: Fetch, dry_run: bool = False
) -> tuple[list[str], list[str]]:
    """Mirror all new versions; return (added versions, errors)."""
    available = discover(get)
    existing = set(mirrored_versions(root))
    added: list[str] = []
    errors: list[str] = []

    for version in sorted(available, key=version_key):
        if version in existing:
            continue
        try:
            spec = fetch_spec(version, available[version], get)
        except MirrorError as err:
            errors.append(str(err))
            continue
        added.append(version)
        if dry_run:
            continue
        target = root / MIRROR_DIR / version / "openapi.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    if not dry_run and (added or not (root / INDEX).exists()):
        (root / INDEX).parent.mkdir(parents=True, exist_ok=True)
        (root / INDEX).write_text(build_index(root), encoding="utf-8")
    return added, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="nur anzeigen, nichts schreiben"
    )
    args = parser.parse_args(argv)

    try:
        added, errors = mirror(ROOT, http_get, args.dry_run)
    except (MirrorError, OSError) as err:
        print(f"FEHLER {err}", file=sys.stderr)
        return 1
    for version in added:
        print(f"neu: {APP} {version}")
    if not added:
        print("keine neue Version")
    for error in errors:
        print(f"FEHLER {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
