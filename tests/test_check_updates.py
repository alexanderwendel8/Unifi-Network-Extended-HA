"""Tests for the update check script (.github/scripts/check_updates.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any

import pytest

SCRIPT = Path(__file__).parents[1] / ".github" / "scripts" / "check_updates.py"
_spec = importlib.util.spec_from_file_location("check_updates", SCRIPT)
check_updates = importlib.util.module_from_spec(_spec)
sys.modules["check_updates"] = check_updates
_spec.loader.exec_module(check_updates)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal repository layout."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "tests.yml").write_text(
        "steps:\n"
        "  - uses: actions/checkout@" + "a" * 40 + " # v7.0.1\n"
        "  - uses: home-assistant/actions/hassfest@" + "b" * 40 + " # 2026.11.0\n"
        "  - uses: actions/setup-python@" + "c" * 40 + " # v7.1.0\n"
        '    with:\n      python-version: "3.13"\n'
        '      python-version: "3.14"\n'
        "  - run: pip install ruff==0.17.5\n"
        '  - run: pip install "pytest-homeassistant-custom-component=='
        '$PLUGIN_VERSION"\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements_test.txt").write_text(
        "pytest-homeassistant-custom-component==0.13.375\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        "| Umgebung | Version |\n|---|---|\n"
        "| Home Assistant | 2026.11.2 (Home Assistant OS 18.4) |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_updates, "ROOT", tmp_path)
    return tmp_path


class FakeSources:
    """Latest versions without network access."""

    def __init__(
        self,
        tags: dict[str, str] | None = None,
        pypi: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.tags = tags or {}
        self.packages = pypi or {}

    def latest_action_tag(self, repo: str) -> str:
        if repo not in self.tags:
            raise OSError("HTTP Error 403: Forbidden")
        return self.tags[repo]

    def pypi(self, package: str) -> dict[str, Any]:
        if package not in self.packages:
            raise OSError("HTTP Error 404: Not Found")
        return self.packages[package]


CURRENT = FakeSources(
    tags={
        "actions/checkout": "v7.0.1",
        "actions/setup-python": "v7.1.0",
        "home-assistant/actions": "2026.11.0",
    },
    pypi={
        "ruff": {"version": "0.17.5"},
        "pytest-homeassistant-custom-component": {"version": "0.13.375"},
        "homeassistant": {"version": "2026.11.3", "requires_python": ">=3.14.2"},
    },
)


class FakeGitHub:
    """Records issue operations."""

    def __init__(self, issues: list[dict[str, Any]] | None = None) -> None:
        self.issues = issues or []
        self.created: list[tuple[str, str]] = []
        self.updated: list[tuple[int, dict[str, Any]]] = []
        self.comments: list[int] = []
        self.label_checked = False

    def ensure_label(self) -> None:
        self.label_checked = True

    def open_issues(self) -> list[dict[str, Any]]:
        return self.issues

    def create_issue(self, title: str, body: str) -> dict[str, Any]:
        self.created.append((title, body))
        return {"number": 100 + len(self.created)}

    def update_issue(self, number: int, **fields: Any) -> None:
        self.updated.append((number, fields))

    def comment(self, number: int, body: str) -> None:
        self.comments.append(number)


def _findings(results: list[Any]) -> dict[str, str]:
    return {r.key: r.finding.title for r in results if r.finding}


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("v7.0.2", "v7.0.1", True),
        ("7.0.1", "v7.0.1", False),
        ("v7.0.10", "v7.0.9", True),
        ("2026.11.0", "2026.12.0", False),
    ],
)
def test_is_newer(latest: str, current: str, expected: bool) -> None:
    """Versions compare numerically, with or without a leading v."""
    assert check_updates.is_newer(latest, current) is expected


def test_is_newer_rejects_unknown_format() -> None:
    """Versions such as 'main' cannot be compared."""
    with pytest.raises(check_updates.CheckError):
        check_updates.is_newer("main", "v1.0.0")


def test_everything_current(repo: Path) -> None:
    """No findings when all components are current."""
    results, errors = check_updates.collect(CURRENT)
    assert errors == []
    assert _findings(results) == {}
    assert {r.key for r in results} == {
        "action:actions/checkout",
        "action:actions/setup-python",
        "action:home-assistant/actions",
        "pypi:ruff",
        "pypi:pytest-homeassistant-custom-component",
        "homeassistant:tested",
        "python:homeassistant",
    }


def test_outdated_components(repo: Path) -> None:
    """Each outdated component gets one finding."""
    sources = FakeSources(
        tags={**CURRENT.tags, "actions/checkout": "v8.0.0"},
        pypi={
            "ruff": {"version": "0.17.6"},
            "pytest-homeassistant-custom-component": {"version": "0.13.380"},
            "homeassistant": {"version": "2026.12.0", "requires_python": ">=3.15.0"},
        },
    )
    results, errors = check_updates.collect(sources)
    assert errors == []
    assert _findings(results) == {
        "action:actions/checkout": (
            "Aktualisierung: GitHub Action actions/checkout v7.0.1 → v8.0.0"
        ),
        "pypi:ruff": "Aktualisierung: ruff 0.17.5 → 0.17.6",
        "pypi:pytest-homeassistant-custom-component": (
            "Aktualisierung: pytest-homeassistant-custom-component 0.13.375 → 0.13.380"
        ),
        "homeassistant:tested": (
            "Home Assistant 2026.12 veröffentlicht – Integration testen"
        ),
        "python:homeassistant": "Home Assistant 2026.12.0 benötigt Python 3.15",
    }


def test_home_assistant_patch_release_is_ignored(repo: Path) -> None:
    """A patch release of the tested month does not create an issue."""
    results, _ = check_updates.collect(CURRENT)
    assert "homeassistant:tested" not in _findings(results)


def test_failed_checks_are_reported(repo: Path) -> None:
    """Network errors become errors instead of findings."""
    results, errors = check_updates.collect(FakeSources())
    assert results == []
    assert check_updates.failed_keys(errors) == {
        "action:actions/checkout",
        "action:actions/setup-python",
        "action:home-assistant/actions",
        "pypi:pytest-homeassistant-custom-component",
        "pypi:ruff",
        "homeassistant",
        "homeassistant:tested",
        "python:homeassistant",
    }


def _issue(number: int, key: str, title: str = "alt") -> dict[str, Any]:
    return {"number": number, "title": title, "body": f"x\n<!-- update-check:{key} -->"}


def test_sync_creates_updates_and_closes() -> None:
    """Issues follow the findings."""
    finding = check_updates.Finding("pypi:ruff", "ruff 0.17.5 → 0.17.6", "Text")
    github = FakeGitHub(
        [
            _issue(1, "pypi:ruff"),
            _issue(2, "action:actions/checkout"),
            _issue(3, "action:removed/action"),
            _issue(4, "action:failed/action"),
            {"number": 5, "title": "Fremdes Issue", "body": "ohne Marker"},
        ]
    )
    results = [
        check_updates.Result("pypi:ruff", finding),
        check_updates.Result("action:actions/checkout", None),
        check_updates.Result(
            "pypi:new", check_updates.Finding("pypi:new", "new 1 → 2", "Text")
        ),
    ]
    log = check_updates.sync_issues(github, results, {"action:failed/action"})

    assert github.label_checked
    assert github.created == [
        ("new 1 → 2", check_updates.issue_body(results[2].finding))
    ]
    assert github.updated == [
        (1, {"title": finding.title, "body": check_updates.issue_body(finding)}),
        (2, {"state": "closed", "state_reason": "completed"}),
        (3, {"state": "closed", "state_reason": "completed"}),
    ]
    assert github.comments == [2, 3]
    assert len(log) == 4


def test_sync_leaves_unchanged_issue_alone() -> None:
    """An issue that already matches the finding is not touched."""
    finding = check_updates.Finding("pypi:ruff", "ruff 0.17.5 → 0.17.6", "Text")
    github = FakeGitHub(
        [
            {
                "number": 1,
                "title": finding.title,
                "body": check_updates.issue_body(finding),
            }
        ]
    )
    log = check_updates.sync_issues(
        github, [check_updates.Result("pypi:ruff", finding)], set()
    )
    assert log == []
    assert github.updated == []
    assert github.created == []
