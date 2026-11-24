"""Tests for the API mirror script (.github/scripts/mirror_api.py)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPT = Path(__file__).parents[1] / ".github" / "scripts" / "mirror_api.py"
_spec = importlib.util.spec_from_file_location("mirror_api", SCRIPT)
mirror_api = importlib.util.module_from_spec(_spec)
sys.modules["mirror_api"] = mirror_api
_spec.loader.exec_module(mirror_api)

ORIGIN = mirror_api.ORIGIN


def _spec_doc(version: str) -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "UniFi Network API", "version": version},
        "paths": {"/v1/info": {"get": {}}, "/v1/sites": {"get": {}, "post": {}}},
    }


def _sitemap(*paths: str) -> str:
    urls = "".join(f"<url><loc>{ORIGIN}/{p}</loc></url>" for p in paths)
    return (
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    )


class FakeSite:
    """Serves documents by URL; unknown URLs fail like a 404."""

    def __init__(self, documents: dict[str, str]) -> None:
        self.documents = documents
        self.requests: list[tuple[str, bool]] = []

    def __call__(self, url: str, rsc: bool) -> str:
        self.requests.append((url, rsc))
        if url not in self.documents:
            raise OSError(f"HTTP Error 404: {url}")
        return self.documents[url]


def _read(root: Path, version: str) -> dict:
    path = root / "docs" / "api" / "network" / version / "openapi.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_mirrors_new_versions_and_keeps_old(tmp_path: Path) -> None:
    """New versions are added; existing and removed ones stay untouched."""
    old = tmp_path / "docs" / "api" / "network" / "v9.0.1" / "openapi.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"kept": true}', encoding="utf-8")
    existing = tmp_path / "docs" / "api" / "network" / "v10.3.58" / "openapi.json"
    existing.parent.mkdir(parents=True)
    existing.write_text(json.dumps(_spec_doc("10.3.58")), encoding="utf-8")

    site = FakeSite(
        {
            f"{ORIGIN}/sitemap.xml": _sitemap(
                "network/v10.3.58/gettingstarted",
                "network/v11.0.97/gettingstarted",
                "network/v11.0.97/getinfo",
                "protect/v7.0.1/gettingstarted",
                "network",
            ),
            f"{ORIGIN}/network/v11.0.97/openapi.json": json.dumps(_spec_doc("11.0.97")),
        }
    )
    added, errors = mirror_api.mirror(tmp_path, site)

    assert (added, errors) == (["v11.0.97"], [])
    assert _read(tmp_path, "v11.0.97") == _spec_doc("11.0.97")
    # v9.0.1 is no longer listed by the source and is kept as it was.
    assert old.read_text(encoding="utf-8") == '{"kept": true}'
    # The existing version was not requested again.
    assert not any("v10.3.58" in url for url, _ in site.requests)
    assert not (tmp_path / "docs" / "api" / "protect").exists()

    index = (tmp_path / "docs" / "api" / "README.md").read_text(encoding="utf-8")
    assert "| 11.0.97 | 2 | 3 |" in index
    assert index.index("11.0.97") < index.index("10.3.58") < index.index("9.0.1")


def test_spec_from_page_data(tmp_path: Path) -> None:
    """Without openapi.json the spec is taken from the page data."""
    page = (
        '1:["$","div",null,{"children":"x"}]\n'
        '2:{"version":"v11.0.97","fullSpec":'
        + json.dumps(_spec_doc("11.0.97"))
        + ',"other":{"a":"}"}}\n'
    )
    site = FakeSite(
        {
            f"{ORIGIN}/sitemap.xml": _sitemap(
                "network/v11.0.97/a-very-long-page-name", "network/v11.0.97/info"
            ),
            # The site answers unknown paths with an HTML page.
            f"{ORIGIN}/network/v11.0.97/openapi.json": "<!DOCTYPE html><html></html>",
            f"{ORIGIN}/network/v11.0.97/info": page,
        }
    )
    added, errors = mirror_api.mirror(tmp_path, site)

    assert (added, errors) == (["v11.0.97"], [])
    assert _read(tmp_path, "v11.0.97") == _spec_doc("11.0.97")
    assert (f"{ORIGIN}/network/v11.0.97/info", True) in site.requests


def test_sitemap_index(tmp_path: Path) -> None:
    """A sitemap index is followed."""
    site = FakeSite(
        {
            f"{ORIGIN}/sitemap.xml": (
                f"<sitemapindex><sitemap><loc>{ORIGIN}/sitemap-0.xml</loc>"
                "</sitemap></sitemapindex>"
            ),
            f"{ORIGIN}/sitemap-0.xml": _sitemap("network/v11.0.97/info"),
        }
    )
    assert mirror_api.discover(site) == {
        "v11.0.97": [f"{ORIGIN}/network/v11.0.97/info"]
    }


def test_errors_do_not_write_files(tmp_path: Path) -> None:
    """A wrong or missing spec is reported; other versions are still mirrored."""
    site = FakeSite(
        {
            f"{ORIGIN}/sitemap.xml": _sitemap(
                "network/v10.4.57/info",
                "network/v10.5.67/info",
                "network/v11.0.97/info",
            ),
            # Declares another version than the URL.
            f"{ORIGIN}/network/v10.4.57/openapi.json": json.dumps(_spec_doc("10.3.58")),
            f"{ORIGIN}/network/v10.5.67/info": "no spec here",
            f"{ORIGIN}/network/v11.0.97/openapi.json": json.dumps(_spec_doc("11.0.97")),
        }
    )
    added, errors = mirror_api.mirror(tmp_path, site)

    assert added == ["v11.0.97"]
    assert errors == [
        "v10.4.57: Spezifikation nennt Version '10.3.58', nicht gespeichert",
        "v10.5.67: keine OpenAPI-Spezifikation gefunden",
    ]
    assert mirror_api.mirrored_versions(tmp_path) == ["v11.0.97"]


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    """--dry-run only reports."""
    site = FakeSite(
        {
            f"{ORIGIN}/sitemap.xml": _sitemap("network/v11.0.97/info"),
            f"{ORIGIN}/network/v11.0.97/openapi.json": json.dumps(_spec_doc("11.0.97")),
        }
    )
    added, errors = mirror_api.mirror(tmp_path, site, dry_run=True)
    assert (added, errors) == (["v11.0.97"], [])
    assert not (tmp_path / "docs").exists()


def test_no_versions_in_sitemap() -> None:
    """A sitemap without versions is an error, not an empty result."""
    site = FakeSite({f"{ORIGIN}/sitemap.xml": _sitemap("network", "protect/v7.0.1/x")})
    with pytest.raises(mirror_api.MirrorError):
        mirror_api.discover(site)
