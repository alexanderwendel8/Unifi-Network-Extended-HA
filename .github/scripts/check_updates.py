#!/usr/bin/env python3
"""Check external components for new versions and keep GitHub issues in sync.

Checked components:

- GitHub Actions in ``.github/workflows`` (pinned to a SHA, version as comment)
- Python packages pinned in ``requirements_test.txt`` and the workflows (PyPI)
- Home Assistant: new release (year.month) compared with the version tested
  in README.md, and the Python version the latest release requires compared
  with the newest Python version in the test matrix

For each outdated component there is exactly one open issue with the label
``aktualisierung``; it is identified by a hidden marker in the body. Issues
whose component is up to date again are closed. A component whose check failed
(e.g. network error) keeps its issue unchanged.

Usage: ``check_updates.py [--dry-run]``. Without ``--dry-run`` the script
needs ``GITHUB_TOKEN`` and ``GITHUB_REPOSITORY`` (set in GitHub Actions).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
LABEL = "aktualisierung"
LABEL_COLOR = "fbca04"
LABEL_DESCRIPTION = "Externe Komponente nicht mehr aktuell (automatisch geprüft)"
MARKER_RE = re.compile(r"<!-- update-check:(\S+) -->")
USER_AGENT = "unifi-network-extended-update-check"

ACTION_RE = re.compile(
    r"uses:\s*(?P<repo>[\w.-]+/[\w.-]+)(?:/[\w./-]+)?@[0-9a-f]{40}\s*#\s*(?P<version>\S+)"
)
PIP_PIN_RE = re.compile(r"(?P<name>[A-Za-z0-9][\w.-]*)==(?P<version>\d[\w.]*)")
README_HA_RE = re.compile(r"^\| Home Assistant \| (?P<version>\d+\.\d+\.\d+)", re.M)
PYTHON_VERSION_RE = re.compile(r"python-version:\s*\"(?P<version>\d+\.\d+)\"")


class CheckError(Exception):
    """Raised when the latest version of a component cannot be determined."""


@dataclass(frozen=True)
class Finding:
    """An outdated component."""

    key: str
    title: str
    body: str


@dataclass(frozen=True)
class Result:
    """Outcome of one check: a finding, or None if the component is current."""

    key: str
    finding: Finding | None


def parse_version(text: str) -> tuple[int, ...] | None:
    """Parse ``1.2.3`` or ``v1.2.3`` into a tuple; None for anything else."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", text.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    """Return True if ``latest`` is a higher version than ``current``."""
    latest_v, current_v = parse_version(latest), parse_version(current)
    if latest_v is None or current_v is None:
        raise CheckError(f"Version nicht vergleichbar: {latest!r} / {current!r}")
    return latest_v > current_v


def http_json(url: str, headers: dict[str, str] | None = None) -> Any:
    """GET a JSON document."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


class Sources:
    """Where the latest versions come from (replaced in tests)."""

    def __init__(self, token: str | None = None) -> None:
        self._api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
        self._github_headers = {"Accept": "application/vnd.github+json"}
        if token:
            self._github_headers["Authorization"] = f"Bearer {token}"

    def pypi(self, package: str) -> dict[str, Any]:
        """Return the ``info`` block of a PyPI project."""
        quoted = urllib.parse.quote(package)
        return http_json(f"https://pypi.org/pypi/{quoted}/json")["info"]

    def latest_action_tag(self, repo: str) -> str:
        """Return the latest release tag of an action, else its highest tag."""
        try:
            release = http_json(
                f"{self._api}/repos/{repo}/releases/latest", self._github_headers
            )
            return release["tag_name"]
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
        tags = http_json(
            f"{self._api}/repos/{repo}/tags?per_page=100", self._github_headers
        )
        versions = [t["name"] for t in tags if parse_version(t["name"]) is not None]
        if not versions:
            raise CheckError(f"{repo}: keine Releases oder Versions-Tags")
        return max(versions, key=lambda name: parse_version(name) or ())


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _workflow_files() -> list[Path]:
    return sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))


def _run(key: str, check: Callable[[], Finding | None]) -> Result:
    """Run one check; a failure raises CheckError tagged with the key."""
    try:
        return Result(key, check())
    except (CheckError, OSError, KeyError, ValueError) as err:
        raise CheckError(f"{key}: {err}") from err


def check_actions(sources: Sources) -> Iterator[Result | CheckError]:
    """Compare each pinned GitHub Action with its latest release."""
    used: dict[str, dict[str, set[str]]] = {}
    for path in _workflow_files():
        for match in ACTION_RE.finditer(path.read_text(encoding="utf-8")):
            files = used.setdefault(match["repo"], {}).setdefault(
                match["version"], set()
            )
            files.add(f".github/workflows/{path.name}")

    for repo, versions in sorted(used.items()):
        key = f"action:{repo}"

        def check(repo: str = repo, versions: dict[str, set[str]] = versions):
            latest = sources.latest_action_tag(repo)
            outdated = {v: f for v, f in versions.items() if is_newer(latest, v)}
            if not outdated:
                return None
            current = ", ".join(sorted(outdated))
            files = sorted(set().union(*outdated.values()))
            return Finding(
                key=f"action:{repo}",
                title=f"Aktualisierung: GitHub Action {repo} {current} → {latest}",
                body="\n".join(
                    [
                        f"Die GitHub Action `{repo}` ist in Version **{latest}** "
                        f"verfügbar; verwendet wird **{current}**.",
                        "",
                        "Verwendet in:",
                        *(f"- `{file}`" for file in files),
                        "",
                        f"Release: https://github.com/{repo}/releases/tag/{latest}",
                        "",
                        "Zu tun: Release Notes auf Breaking Changes prüfen, Commit-SHA "
                        "und Versionskommentar aktualisieren. Dependabot schlägt das "
                        "oft schon als Pull Request vor.",
                    ]
                ),
            )

        try:
            yield _run(key, check)
        except CheckError as err:
            yield err


def _pinned_packages() -> dict[str, tuple[str, str]]:
    """Return {package: (version, file)} for exact pins we maintain."""
    pins: dict[str, tuple[str, str]] = {}
    for line in _read("requirements_test.txt").splitlines():
        if match := PIP_PIN_RE.fullmatch(line.split("#")[0].strip()):
            pins[match["name"].lower()] = (match["version"], "requirements_test.txt")
    for path in _workflow_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            # Only plain `pip install pkg==x` lines; matrix values such as
            # "$PLUGIN_VERSION" are intentionally old versions.
            if "pip install" not in line or "$" in line:
                continue
            for match in PIP_PIN_RE.finditer(line):
                pins.setdefault(
                    match["name"].lower(),
                    (match["version"], f".github/workflows/{path.name}"),
                )
    return pins


def check_python_packages(sources: Sources) -> Iterator[Result | CheckError]:
    """Compare pinned Python packages with the latest release on PyPI."""
    for name, (version, file) in sorted(_pinned_packages().items()):
        key = f"pypi:{name}"

        def check(name: str = name, version: str = version, file: str = file):
            latest = sources.pypi(name)["version"]
            if not is_newer(latest, version):
                return None
            return Finding(
                key=f"pypi:{name}",
                title=f"Aktualisierung: {name} {version} → {latest}",
                body="\n".join(
                    [
                        f"`{name}` ist in Version **{latest}** verfügbar; "
                        f"festgelegt ist **{version}** in `{file}`.",
                        "",
                        f"PyPI: https://pypi.org/project/{name}/{latest}/",
                        "",
                        "Zu tun: Änderungen prüfen, Version anheben, Tests und Lint "
                        "laufen lassen.",
                    ]
                ),
            )

        try:
            yield _run(key, check)
        except CheckError as err:
            yield err


def check_home_assistant(sources: Sources) -> Iterator[Result | CheckError]:
    """Check for a new Home Assistant release and its required Python version."""
    try:
        info = sources.pypi("homeassistant")
    except (OSError, KeyError, ValueError) as err:
        yield CheckError(f"homeassistant: {err}")
        return

    def check_tested() -> Finding | None:
        match = README_HA_RE.search(_read("README.md"))
        if match is None:
            raise CheckError("README.md: Zeile '| Home Assistant | …' nicht gefunden")
        tested, latest = match["version"], info["version"]
        tested_v, latest_v = parse_version(tested), parse_version(latest)
        if tested_v is None or latest_v is None:
            raise CheckError(f"Version nicht vergleichbar: {latest!r} / {tested!r}")
        # Only new monthly releases (year.month); patch releases follow often.
        if latest_v[:2] <= tested_v[:2]:
            return None
        release = ".".join(str(part) for part in latest_v[:2])
        return Finding(
            key="homeassistant:tested",
            title=f"Home Assistant {release} veröffentlicht – Integration testen",
            body="\n".join(
                [
                    f"Home Assistant **{latest}** ist verfügbar; laut README getestet "
                    f"ist **{tested}**.",
                    "",
                    f"Release Notes: https://www.home-assistant.io/blog/categories/"
                    f"release-notes/ (Version {release})",
                    "",
                    "Zu tun: Release Notes und Entwickler-Blog auf Änderungen prüfen, "
                    "die die Integration betreffen (Deprecations, neue Anforderungen), "
                    "auf dem Testsystem testen und die Tabelle „Getestete Geräte“ im "
                    "README aktualisieren.",
                ]
            ),
        )

    def check_python() -> Finding | None:
        match = re.search(r">=\s*(\d+)\.(\d+)", info.get("requires_python") or "")
        if match is None:
            raise CheckError(
                f"requires_python unbekannt: {info.get('requires_python')!r}"
            )
        required = (int(match[1]), int(match[2]))
        tested = [
            parse_version(m["version"])
            for path in _workflow_files()
            for m in PYTHON_VERSION_RE.finditer(path.read_text(encoding="utf-8"))
        ]
        newest = max((v for v in tested if v), default=None)
        if newest is None:
            raise CheckError("keine python-version in den Workflows gefunden")
        if required <= newest[:2]:
            return None
        required_s = f"{required[0]}.{required[1]}"
        return Finding(
            key="python:homeassistant",
            title=f"Home Assistant {info['version']} benötigt Python {required_s}",
            body="\n".join(
                [
                    f"Home Assistant **{info['version']}** verlangt "
                    f"`{info['requires_python']}`; die neueste Python-Version in den "
                    f"Workflows ist **{'.'.join(map(str, newest))}**.",
                    "",
                    "Zu tun: Python-Version für den Matrix-Eintrag „current“ in "
                    "`.github/workflows/tests.yml` anheben; die bisherige Version "
                    "wird zum Eintrag „letzte Version für Python …“ (siehe CLAUDE.md).",
                ]
            ),
        )

    for key, check in (
        ("homeassistant:tested", check_tested),
        ("python:homeassistant", check_python),
    ):
        try:
            yield _run(key, check)
        except CheckError as err:
            yield err


CHECKS = (check_actions, check_python_packages, check_home_assistant)


def collect(sources: Sources) -> tuple[list[Result], list[CheckError]]:
    """Run all checks."""
    results: list[Result] = []
    errors: list[CheckError] = []
    for check in CHECKS:
        for item in check(sources):
            (errors if isinstance(item, CheckError) else results).append(item)
    return results, errors


def failed_keys(errors: list[CheckError]) -> set[str]:
    """Keys whose check failed; ``homeassistant`` stands for both HA checks."""
    keys: set[str] = set()
    for err in errors:
        key = str(err).split(": ", 1)[0]
        if key == "homeassistant":
            keys |= {"homeassistant:tested", "python:homeassistant"}
        keys.add(key)
    return keys


class GitHub:
    """Minimal GitHub issues API client."""

    def __init__(self, token: str, repository: str) -> None:
        self._token = token
        api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
        self._base = f"{api}/repos/{repository}"

    def _request(self, method: str, path: str, data: Any = None) -> Any:
        request = urllib.request.Request(
            f"{self._base}{path}",
            method=method,
            data=None if data is None else json.dumps(data).encode(),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
        return json.loads(content) if content else None

    def ensure_label(self) -> None:
        try:
            self._request("GET", f"/labels/{urllib.parse.quote(LABEL)}")
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
            self._request(
                "POST",
                "/labels",
                {"name": LABEL, "color": LABEL_COLOR, "description": LABEL_DESCRIPTION},
            )

    def open_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self._request(
                "GET", f"/issues?state=open&labels={LABEL}&per_page=100&page={page}"
            )
            issues += [i for i in batch if "pull_request" not in i]
            if len(batch) < 100:
                return issues
            page += 1

    def create_issue(self, title: str, body: str) -> dict[str, Any]:
        return self._request(
            "POST", "/issues", {"title": title, "body": body, "labels": [LABEL]}
        )

    def update_issue(self, number: int, **fields: Any) -> None:
        self._request("PATCH", f"/issues/{number}", fields)

    def comment(self, number: int, body: str) -> None:
        self._request("POST", f"/issues/{number}/comments", {"body": body})


def issue_body(finding: Finding) -> str:
    """Body with the hidden marker that identifies the component."""
    return (
        f"{finding.body}\n\n---\n_Automatisch angelegt vom Workflow "
        f"`update-check.yml`. Das Issue wird geschlossen, sobald die Komponente "
        f"aktuell ist._\n\n<!-- update-check:{finding.key} -->"
    )


def sync_issues(github: GitHub, results: list[Result], failed: set[str]) -> list[str]:
    """Create, update and close issues; return a log of the actions."""
    log: list[str] = []
    github.ensure_label()
    existing: dict[str, dict[str, Any]] = {}
    for issue in github.open_issues():
        if match := MARKER_RE.search(issue.get("body") or ""):
            existing[match[1]] = issue

    for result in results:
        issue = existing.get(result.key)
        if result.finding is None:
            if issue is not None:
                github.comment(
                    issue["number"], "Die Komponente ist jetzt aktuell. Erledigt."
                )
                github.update_issue(
                    issue["number"], state="closed", state_reason="completed"
                )
                log.append(f"geschlossen #{issue['number']}: {result.key}")
            continue
        body = issue_body(result.finding)
        if issue is None:
            created = github.create_issue(result.finding.title, body)
            log.append(f"angelegt #{created['number']}: {result.finding.title}")
        elif issue["title"] != result.finding.title or issue.get("body") != body:
            github.update_issue(issue["number"], title=result.finding.title, body=body)
            log.append(f"aktualisiert #{issue['number']}: {result.finding.title}")

    # Components no longer used at all (e.g. an action removed from the
    # workflows). Keep issues whose check failed this time.
    checked = {result.key for result in results}
    for key, issue in existing.items():
        if key not in checked and key not in failed:
            github.comment(
                issue["number"], "Die Komponente wird nicht mehr verwendet. Erledigt."
            )
            github.update_issue(
                issue["number"], state="closed", state_reason="completed"
            )
            log.append(f"geschlossen #{issue['number']}: {key} (nicht mehr verwendet)")
    return log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="nur anzeigen, keine Issues ändern"
    )
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN")
    results, errors = collect(Sources(token))
    for result in results:
        status = result.finding.title if result.finding else "aktuell"
        print(f"{result.key}: {status}")
    for err in errors:
        print(f"FEHLER {err}", file=sys.stderr)

    if not args.dry_run:
        repository = os.environ.get("GITHUB_REPOSITORY")
        if not token or not repository:
            print("GITHUB_TOKEN und GITHUB_REPOSITORY fehlen", file=sys.stderr)
            return 2
        for line in sync_issues(
            GitHub(token, repository), results, failed_keys(errors)
        ):
            print(line)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
