# UniFi Network Extended for Home Assistant

**Language:** [Deutsch](README.md) · English

[![Tests](https://github.com/alexanderwendel8/Unifi-Network-Extended-HA/actions/workflows/tests.yml/badge.svg)](https://github.com/alexanderwendel8/Unifi-Network-Extended-HA/actions/workflows/tests.yml) [![Validate](https://github.com/alexanderwendel8/Unifi-Network-Extended-HA/actions/workflows/validate.yml/badge.svg)](https://github.com/alexanderwendel8/Unifi-Network-Extended-HA/actions/workflows/validate.yml)

Custom integration for Home Assistant that connects a UniFi Network application
(for example on a UniFi OS console such as UCG, UDM or Cloud Key) through the
**official UniFi Network API** – with an API key instead of a username and
password, and without unofficial endpoints. The specification in use is at
[`docs/unifi-network-api.openapi.json`](docs/unifi-network-api.openapi.json)
(UniFi Network API 11.0.97).

**What the integration offers:**
- **Gateways, switches and access points** as devices with state, CPU and
  memory utilization, uplink rates, last restart, firmware update notice,
  connected clients, uplink device (network topology) and a *Restart* button
- **Every switch port** with link and speed, PoE ports also with PoE state and
  a *PoE power cycle* button
- **Every radio band** of the access points with channel, channel width, Wi-Fi
  standard and TX retries
- **Clients** as a count per site and per device, and optionally as device
  trackers for presence detection

Setup and configuration are done entirely in the Home Assistant user interface.

> **Status:** Version 0.2.0 – tested on a real UniFi network
> (see [Tested devices](#tested-devices)).

## Tested devices

Tested on a real UniFi network with the following environment and devices:

| Environment | Version |
|---|---|
| Home Assistant | 2026.11.2 (Home Assistant OS 18.4) |
| UniFi Network Extended | 0.2.0 |
| UniFi Network API (specification) | 11.0.97 |
| UniFi Network application (sensor *UniFi Network version*) | 11.0.104 |

| Device | Type | Firmware |
|---|---|---|
| UCG Max | Cloud gateway (console running UniFi Network) | 6.0.17 |
| USW Pro Max 16 PoE | Switch, PoE | 7.5.15 |
| USW Flex 2.5G 8 PoE | Switch, PoE | 2.1.8 |
| USW Flex 2.5G 5 | Switch | 2.1.8 |
| UDB Switch | Device bridge (wireless bridge with switch) | 8.8.14 |
| U7 Pro Max | Access point, Wi-Fi 7 | 8.8.14 |
| U7 Pro | Access point, Wi-Fi 7 | 8.8.14 |
| U7-Pro-Wall | Access point, Wi-Fi 7 | 8.8.14 |
| U7 Mesh | Access point, Wi-Fi 7 | 8.8.14 |

**Verified on the real network:** setup with API key and site, all sensors and
binary sensors for site, devices, ports and radio bands, the uplink topology,
clients per device, loading in the background (setup in about 1.5 s), stable
values across reloads and restarts of Home Assistant, and installation and
updates through the Marketplace.

**Not yet verified on the real network** (automated tests only): the *Restart*
and *PoE power cycle* buttons, reconfiguration and reauthentication, multiple
sites and self-hosted UniFi Network servers.

Further feedback on devices is welcome as an
[issue](https://github.com/alexanderwendel8/Unifi-Network-Extended-HA/issues).

## Installation

**Requirement:** Home Assistant **2025.8.0** or newer (as stated in
[`hacs.json`](hacs.json)). The automated tests run against this minimum
version, against 2026.2 (last version for Python 3.13) and against the current
version.

The integration is not (yet) part of the official catalog and is added as a
**custom repository**.

### Marketplace (Home Assistant 2026.11 and newer)

Since Home Assistant 2026.11, HACS is built into Home Assistant as the
**Marketplace**; HACS no longer has to be installed separately (and can no
longer be installed from 2026.11 on).

1. Open *Settings → Marketplace*.
2. Select **Add from link** in the upper-right corner.
3. Under **GitHub link**, enter `https://github.com/alexanderwendel8/Unifi-Network-Extended-HA`
   and select **Add**. If the type is not detected, select *Integration* under
   **Type** and select **Add** again.
4. Open “UniFi Network Extended” in the list, install it and restart Home
   Assistant when a repair asks you to.

To add a custom repository, the Marketplace requires a connection to GitHub
(read access to public data only). New versions are then checked every 48 hours
and offered under *Settings → Updates*; after an update you restart Home
Assistant through the repair that is shown. By default only stable
[releases](#releases) are offered, no pre-releases.

(Labels as in the documentation of the
[Marketplace integration](https://www.home-assistant.io/integrations/marketplace/).)

### HACS (up to Home Assistant 2026.10)

1. HACS → Integrations → ⋮ → *Custom repositories*
2. Add the URL of this repository, category *Integration*
3. Install “UniFi Network Extended” and restart Home Assistant

When you update to Home Assistant 2026.11, the Marketplace takes over the
integration installed with HACS automatically – including the custom repository
and the update entity. There is nothing else to do.

### Manual
Copy the folder `custom_components/unifi_network_extended` to
`<config>/custom_components/` and restart Home Assistant.

## Setup

*Settings → Devices & services → Add integration → “UniFi Network Extended”*

| Field | Description |
|---|---|
| Host | Hostname, IPv4 or IPv6 address of the controller, without `https://` (e.g. `192.168.1.1`, `unifi.local`, `fd00::1`). A pasted `https://`, a path or a port (`unifi.local:8443`, `[fd00::1]:8443`) is cleaned up automatically or moved to the Port field |
| Port | usually `443` |
| API key | Created in the *Integrations* section of the UniFi Network application |
| Verify SSL certificate | Only disable for self-signed certificates |

After that the sites are fetched with `GET /v1/sites` – which also checks the
API key. If there is only one site, it is used automatically; otherwise you
pick it from a list. Each site gets its own entry; for further sites simply add
the integration again (sites that are already set up are no longer offered).

On startup the integration checks whether the site still exists.
Host, port, API key and the SSL option can be changed later with
*⋮ → Reconfigure* (the site stays fixed). If the API key becomes invalid,
Home Assistant asks for a new one automatically.

## Entities

**Site** (one device per site)
- Connected clients in total, wired and wireless
- VPN and guest clients (disabled by default)
- Number of adopted devices
- UniFi Network version (diagnostic): version of the UniFi Network application,
  also shown as the firmware version of the site device; checked hourly
  (`GET /v1/info`)

**Per UniFi device** (gateway, switch, access point …)
- State (Online, Offline, Updating, …)
- Firmware update available (binary sensor)
- CPU and memory utilization, uplink download and upload rate
- Last restart, IP address
- Connected clients (directly on this switch or access point)
- Uplink device (which device it is connected to) and time of the last provisioning (diagnostic)
- Firmware version and load average (disabled by default)
- *Restart* button (only available while the device is online)

**Per radio band** (access points, each of 2.4 / 5 / 6 GHz)
- Channel, channel width and Wi-Fi standard (diagnostic)
- TX power as a mode (Auto, Low, Medium, High, Custom, Disabled;
  diagnostic, from UniFi Network 11.0)
- TX retries in % (share of retransmitted packets, a sign of interference or
  overload)

**Per port** (switches, gateways with switch ports)
- Link (connected/disconnected)
- Current speed (diagnostic)
- Maximum speed and connector type (RJ45, SFP, SFP+ …) (diagnostic, disabled by
  default)
- PoE ports only: PoE state (Supplying power, Off, Limited; diagnostic) and the
  *PoE power cycle* button (for example for stuck cameras or access points);
  both only enabled where PoE is switched on. PoE enabled, PoE standard and
  PoE type as diagnostics (disabled by default)

On the device page, each port therefore only has its link under “Sensors”;
everything else is under “Diagnostic”.

PoE cannot be switched on or off permanently through the official API, and the
power draw is not provided.

Statistics and port values only exist for devices that are online.
They are loaded in the background after startup; until then the statistics
sensors are briefly unavailable and the port entities appear as soon as their
data is there. Newly adopted devices get their entities automatically, without
a restart.

Devices that UniFi no longer reports (for example after “Forget device”, a
return or a replacement) are removed from Home Assistant together with their
entities after the next successful update, also if that happened during a
restart of Home Assistant. UniFi keeps reporting offline devices, so they are
kept. If an update fails, nothing is removed. Such a device can also be deleted
by hand on its device page; devices that UniFi still reports and the site
device cannot. If a removed device is adopted again, it gets new entities.

**Clients** (device trackers)
- For every wired or wireless client with a MAC address: *home* while it is
  connected. VPN connections are not tracked.
- As with other router integrations, Home Assistant creates the trackers
  disabled (up to version 2026.x only if no device with the same MAC address is
  known yet). You can enable the trackers you want one by one; they are then
  assigned to the device with that MAC address, for example the smartphone from
  the Companion app, otherwise a separate device is created.
- Trackers of clients that have not been connected for **180 days** are removed
  automatically, also enabled ones. This is checked on startup and then once a
  day. A device that was only created for the tracker disappears with it;
  devices of other integrations (for example the smartphone from the Companion
  app) are kept. This keeps the entity registry from growing because of guests
  or changing private Wi-Fi addresses of smartphones.
- The API only returns connected clients. The integration therefore stores the
  time of the last connection itself (in `.storage/`, deleted when the
  integration is removed). For trackers that existed before the update, the
  period starts with the first startup.
- If the client shows up again later, a tracker is created again. It is
  disabled as usual until you enable it. Exception: Home Assistant remembers
  the settings of removed entities (entity ID, name, area, enabled/disabled)
  and restores them; a tracker that was enabled before therefore comes back
  enabled and with the same entity ID
  (source: [`entity_registry.py`](https://github.com/home-assistant/core/blob/2026.11.2/homeassistant/helpers/entity_registry.py),
  `async_get_or_create`).
- **Note for automations:** Between removal and reappearance the entity does
  not exist. Automations and scripts that use such a tracker then do not
  trigger, or their conditions are not met. For presence detection, only use
  devices that connect regularly and use a fixed MAC address (on smartphones,
  switch off the private Wi-Fi address for the home network).

## Icons

The integration logo is at `custom_components/unifi_network_extended/brand/`
and is shown for the integration and its devices from Home Assistant 2026.3
(older versions show a placeholder). It is an original design and not the UniFi
logo of Ubiquiti. The entity icons are defined in `icons.json`.

## Updates and options

The official UniFi Network API offers no push notifications (no WebSocket, no
webhooks). The integration therefore polls the data regularly. Adjustable under
*⋮ → Options*:

| Option | Default | Note |
|---|---|---|
| Update interval for devices and clients | 30 s | min. 10 s |
| Update interval for device statistics and details | 60 s | min. 30 s; two requests per device (statistics, details with ports and uplink) |
| Track clients | on | Trackers of clients that have not been connected for 180 days are removed automatically (also enabled ones; if the client returns, a new tracker is created); switching it off removes all trackers and the stored connection times |

The version of the UniFi Network application is fetched independently of this
on startup and then hourly. If that request fails, the integration still
starts; the sensor is then unavailable until the next successful request, and
the version stored on the site device is kept.

## Storage of the API key

The data is stored – as with all core integrations – in the config entry of
Home Assistant (`<config>/.storage/core.config_entries`), not in
`configuration.yaml`. In addition:

- The API key is shown as a masked field in the UI and never pre-filled.
- API key and host are redacted in diagnostics and not logged.
  Diagnostics contain no client names or addresses.
- SSL verification is enabled by default.
- No user password is stored; the API key can be revoked in UniFi at any time.

Protect the `.storage` directory and your backups accordingly
(Home Assistant backups can be encrypted).

## Development

On every push and pull request, GitHub automatically runs:
- **Tests:** `pytest` with Python 3.13 and 3.14 (older and current Home
  Assistant versions) and `ruff` (lint and formatting)
- **Validate:** `hassfest` (validation by Home Assistant) and the HACS check

The GitHub Actions in use are pinned to a commit SHA with the version as a comment.
[Dependabot](.github/dependabot.yml) checks for new versions weekly and proposes updates as
pull requests.

In addition, the workflow [`update-check.yml`](.github/workflows/update-check.yml) checks all
external components every Monday and opens an issue with the label `aktualisierung` for every
outdated component:
- **GitHub Actions** in `.github/workflows` (new release)
- **Python packages** pinned in `requirements_test.txt` or in the workflows
  (for example `ruff`, `pytest-homeassistant-custom-component`)
- **Home Assistant:** a new monthly release compared with the version tested in the README, and
  a higher minimum Python version than in the test matrix
- **UniFi Network API:** a newer mirrored version than the one the integration is developed against

Once the component is up to date again, the workflow closes the issue itself. The checks are in
[`.github/scripts/check_updates.py`](.github/scripts/check_updates.py); locally,
`python .github/scripts/check_updates.py --dry-run` shows the result without changing issues.

The workflow [`api-mirror.yml`](.github/workflows/api-mirror.yml) mirrors the official
specifications of the UniFi Network API from <https://developer.ui.com/network> to
[`docs/api/`](docs/api/README.md) every Monday, one file per version. Existing versions are never
changed or deleted. The workflow commits new files directly to `main`.

New features are developed exclusively against the official API in
`docs/unifi-network-api.openapi.json` (see `CLAUDE.md`).

```bash
pip install -r requirements_test.txt
pytest
```

README and changelog exist in German (`README.md`, `CHANGELOG.md`) and English (`README.en.md`,
`CHANGELOG.en.md`). Both versions are maintained together: every change goes into both files, with
the same structure. A test (`tests/test_docs.py`) checks that the headings and changelog entries
match.

### Test coverage

Coverage (lines and branches) is measured by `pytest-cov`, which is installed with
`pytest-homeassistant-custom-component`. The settings are in `pyproject.toml`
(`[tool.coverage.*]`), the command follows the
[Home Assistant developer documentation](https://github.com/home-assistant/developers.home-assistant/blob/master/docs/development_testing.md):

```bash
pytest --cov --cov-report=term-missing
```

`Missing` lists the lines and branches that were not executed. `--cov-report=html` additionally
creates a report in `htmlcov/`. The CI shows the coverage in the log and in the summary of the
Actions run and fails if it drops below 97 % (`--cov-fail-under=97` in
`.github/workflows/tests.yml`).

## Releases

Changes are listed in [`CHANGELOG.en.md`](CHANGELOG.en.md) (German: [`CHANGELOG.md`](CHANGELOG.md));
whatever is not part of a release yet is under “Unreleased”. Releases are created by the workflow
`release.yml` with the notes from the German changelog – either through a tag `vX.Y.Z` or
manually under *Actions → Release → Run workflow* (on `main`, input e.g. `0.1.0`; the tag is then
set). The version has to match `manifest.json`. Marketplace and HACS then show the version number
instead of the commit hash and offer new releases as updates.

### Pre-releases

The Marketplace only reports releases as updates, not individual commits on `main`
([source code](https://github.com/home-assistant/core/blob/2026.11.2/homeassistant/components/marketplace/repositories/base.py)).
For testing before a release, the workflow `prerelease.yml` creates a pre-release from the
current state of `main`: *Actions → Pre-release → Run workflow*, the input is the planned next
version, e.g. `0.4.0`. This creates `v0.4.0b1`, the next run `v0.4.0b2` and so on, with the notes
from “Unreleased”. No pull request is needed; `main` stays unchanged (the version `0.4.0b1` only
exists in the commit of the tag).

The Marketplace only offers pre-releases if the **Pre-release** switch of the repository is on:
*Settings → Devices & services → Marketplace → UniFi Network Extended*, enable the **Pre-release**
entity there (disabled by default) and turn it on
([documentation](https://www.home-assistant.io/integrations/marketplace)). Everyone else keeps
getting stable releases only.
