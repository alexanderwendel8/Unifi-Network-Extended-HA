"""The German and English README and changelog must stay in sync."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).parents[1]

# German changelog section -> English changelog section.
CHANGELOG_SECTIONS = {
    "Neu": "New",
    "Geändert": "Changed",
    "Entitäten": "Entities",
    "Einrichtung": "Setup",
    "Behoben": "Fixed",
    "Dokumentation": "Documentation",
    "Entwicklung": "Development",
    "Sonstiges": "Other",
}


def _lines(name: str) -> list[str]:
    """Lines of a document without fenced code blocks."""
    lines: list[str] = []
    in_code = False
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code:
            lines.append(line)
    return lines


def _heading_levels(name: str) -> list[int]:
    return [
        len(match[1]) for line in _lines(name) if (match := re.match(r"(#+) ", line))
    ]


def _changelog(name: str) -> list[tuple[str, str, int]]:
    """Return (version, section, number of entries) for every section."""
    result: list[tuple[str, str, int]] = []
    version = section = ""
    entries = 0
    for line in [*_lines(name), "## end"]:
        if line.startswith(("## ", "### ")):
            if section:
                result.append((version, section, entries))
            entries = 0
            if line.startswith("## "):
                version, section = line[3:], ""
            else:
                section = line[4:]
        elif line.startswith("- "):
            entries += 1
    return result


@pytest.mark.parametrize(
    ("german", "english"),
    [("README.md", "README.en.md"), ("CHANGELOG.md", "CHANGELOG.en.md")],
)
def test_same_structure(german: str, english: str) -> None:
    """Both language versions have the same heading structure and link each other."""
    assert _heading_levels(german) == _heading_levels(english)
    assert f"]({english})" in (ROOT / german).read_text(encoding="utf-8")
    assert f"]({german})" in (ROOT / english).read_text(encoding="utf-8")


def test_changelog_entries_match() -> None:
    """Same versions, same sections and the same number of entries per section."""
    german = _changelog("CHANGELOG.md")
    assert german, "no sections found"
    unknown = {section for _, section, _ in german} - set(CHANGELOG_SECTIONS)
    assert not unknown, f"add to CHANGELOG_SECTIONS: {unknown}"
    translated = [
        (version, CHANGELOG_SECTIONS[section], entries)
        for version, section, entries in german
    ]
    assert translated == _changelog("CHANGELOG.en.md")


def test_readme_tables_match() -> None:
    """Both READMEs have the same number of table rows and list items."""

    def count(name: str) -> tuple[int, int]:
        lines = _lines(name)
        return (
            sum(line.startswith("|") for line in lines),
            sum(bool(re.match(r"\s*(- |\d+\. )", line)) for line in lines),
        )

    assert count("README.md") == count("README.en.md")
