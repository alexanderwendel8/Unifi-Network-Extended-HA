# Changelog

**Language:** [Deutsch](CHANGELOG.md) · English

All notable changes to this integration. New entries first go under “Unreleased”; with the
next release that section becomes the version number.

## Unreleased

### Entities

- The port sensors **link speed** and **PoE state** are now listed under “Diagnostic” instead of
  “Sensors” on the device page; under “Sensors” each port only keeps its link. This matches the
  classification in the official UniFi integration. Entity IDs, values, history and automations
  stay unchanged.
- The channel width per radio band is shown without decimal places (e.g. “160 MHz”).
- New sensor **TX power mode** per radio band of an access point (diagnostic): the configured
  mode Auto, Low, Medium, High, Custom or Disabled. UniFi provides the value from UniFi Network
  11.0; with older versions the sensor is not created. After updating UniFi Network to 11.0 it
  appears once the integration is reloaded.

### Changed

- Development now targets UniFi Network API **11.0.97** instead of 10.3.58 (#39):
  `docs/unifi-network-api.openapi.json` is the official file from the mirror. No endpoints were
  added or removed. Radio bands at 0.9 GHz and the Wi-Fi standard 802.11ah (Wi-Fi HaLow) are
  shown like the other bands.

### Fixed

- On connection errors (timeout, connection refused) the log message “Error fetching … data:”
  was empty. It now contains the request and the kind of error, e.g.
  `GET /v1/sites/…/devices: cannot connect (timeout)`, still without host and API key. The
  related debug message used to contain the aiohttp error text and therefore possibly the host;
  it has been removed.

### Documentation

- README and changelog are now also available in English (`README.en.md`, `CHANGELOG.en.md`).
  Both language versions are maintained together; a test checks that headings and changelog
  entries match.

### Development

- New workflow `prerelease.yml`: manually creates a pre-release (`vX.Y.Zb1`, `b2` …) from the
  current state of `main`, with the notes from “Unreleased”. This allows testing changes through
  the Marketplace (switch “Pre-release” of the repository) without making a release.
- New workflow `api-mirror.yml`: mirrors the official specifications of the UniFi Network API
  from developer.ui.com to `docs/api/network/<version>/openapi.json` every Monday (overview in
  `docs/api/README.md`). Existing versions are never changed or deleted. Logic in
  `.github/scripts/mirror_api.py`, with tests.
- `update-check.yml` opens an issue when a newer API version has been mirrored than the one the
  integration is developed against (`docs/unifi-network-api.openapi.json`).

## 0.3.0

Options are reloaded by Home Assistant's built-in reload; this now requires
**Home Assistant 2025.8.0 or newer**. Also a weekly automatic check of external components.
Tested on a real UniFi network so far is 0.2.0; 0.3.0 is covered by the automated tests
(Home Assistant 2025.8.0 to current).

### Changed
- Options use Home Assistant's automatic reload (`OptionsFlowWithReload`) instead of a custom
  update listener. Changing the update interval or “Track clients” still takes effect immediately
  and reloads the entry exactly once; “Reconfigure” and reauthentication also reload exactly
  once. This removes the warning “has an update listener and should use it for scheduling a
  reload” that Home Assistant has logged since 2026.6 on “Reconfigure” and reauthentication.
- Minimum Home Assistant version raised to **2025.8.0** (first version with
  `OptionsFlowWithReload`); `hacs.json`, README, `CLAUDE.md` and the test workflow adjusted.

### Documentation

- README: tested version updated to 0.2.0 (status line and table “Tested devices”).

### Development

- New workflow `update-check.yml`: checks GitHub Actions, pinned Python packages and new Home
  Assistant releases (including the minimum Python version) every Monday and opens an issue with
  the label `aktualisierung` for every outdated component. Once the component is up to date
  again, the issue is closed. Logic in `.github/scripts/check_updates.py`, with tests.
- `ruff` also checks `.github/scripts`.
- `ruff` updated to 0.17.6 (#34).
- `CLAUDE.md`: open issues with the label `aktualisierung` are reviewed at the start of every
  session; they are only worked on after asking.

## 0.2.0

Clean-up and more robust setup: devices that UniFi no longer reports and client trackers after
180 days without a connection are removed; the host input accepts IPv6 addresses and is cleaned
up; no more double reload after “Reconfigure”.

### Changed
- Device trackers of clients that have not been connected for 180 days are removed automatically,
  also enabled ones (checked on startup and daily). A device that was only created for the
  tracker is removed with it, devices of other integrations are kept. The time of the last
  connection is stored per config entry; existing trackers start their period with the first
  startup after the update. If the client returns, a tracker is created again.
- Switching off “Track clients” also deletes the stored connection times, and removing the
  integration deletes its storage file.

### Entities
- Devices that UniFi no longer reports are removed from Home Assistant together with their
  entities after the next successful update (also on startup); such devices can also be deleted by
  hand in the user interface. Offline devices, devices with invalid API data (see 0.1.1) and the
  site device are kept; a device that is adopted again gets entities again.

### Setup
- Host as hostname, IPv4 or IPv6 address; IPv6 addresses are correctly put in square brackets in
  the URL (e.g. `https://[fd00::1]:443/...`)
- The host input is cleaned up (setup and reconfigure): spaces, `http://`/`https://`, a trailing
  `/` or path and square brackets around IPv6 addresses are removed
- A port in the host input (`unifi.local:8443`, `[fd00::1]:8443`) is moved to the Port field
- Invalid hosts are rejected with the error “Invalid host” instead of attempting a connection
- When reconfiguring, the input is kept in the form after an error

### Fixed
- Reconfigure and reauthentication reload the integration only once instead of twice.
  The options listener only reloads when the options have changed.

### Documentation
- Changelog: section “Unreleased” for ongoing changes; release process adjusted accordingly
- README: “Tested devices” names version 0.1.1 and the UniFi Network application 11.0.104

### Development
- GitHub Actions pinned to a commit SHA with a version comment and updated (Node.js 24):
  `actions/checkout` v7.0.1, `actions/setup-python` v7.1.0, `softprops/action-gh-release` v3.0.4,
  `home-assistant/actions/hassfest` 2026.11.0, `hacs/action` 22.5.0
- Dependabot proposes updates of the GitHub Actions weekly as pull requests

## 0.1.1

Maintenance release: more robust handling of the API data, an up-to-date device registry and the
version of the UniFi Network application as a sensor.

### New
- **Site:** diagnostic sensor *UniFi Network version* with the version of the UniFi Network
  application (`GET /v1/info`); the same version is shown as the firmware version of the site
  device and in the diagnostics. Fetched on startup and then hourly; an error there does not
  prevent startup, an invalid API key starts reauthentication.

### Fixed
- Firmware version and name of the UniFi devices are updated in the Home Assistant device
  registry on every update, without reloading the integration. A name assigned in Home Assistant
  is kept.
- A single record of the UniFi API with an unexpected structure (missing required field or
  unexpected type, e.g. after a firmware update or with a new device type) no longer makes all
  entities unavailable: affected sites, devices, clients, ports and radio bands are skipped, all
  others keep working.
- If the statistics or details of a device cannot be read, this only affects that device.
- Invalid JSON (e.g. an HTML page instead of an API response) is reported as an unexpected
  response, no longer as “cannot connect”.
- Skipped data is logged once per cause as a warning, with endpoint and field name, but without
  API key, host, names, MAC addresses or IDs.

### Documentation
- README: introduction revised; new section “Tested devices” (Home Assistant 2026.11.2, devices
  with firmware version, what is verified on the real network and what is not) (#14)
- README: installation through the Marketplace (Home Assistant 2026.11 and newer), through HACS
  (up to 2026.10) and automatic takeover of existing HACS installations (#15)
- Development rules (`CLAUDE.md`): questions about Home Assistant are answered with the official
  Home Assistant documentation (#16)

### Other
- Minimum Home Assistant version 2025.3.0 (as before in `hacs.json`) verified and named in the
  README; the CI now tests 2025.3.0, 2026.2.3 and the current version with pinned versions of
  `pytest-homeassistant-custom-component` (current version updated by Dependabot)

### Development
- Test coverage is measured in the CI (lines and branches) and shown in the log and in the summary
  of the Actions run; the run fails below 97 %
- New tests for error paths: error text from the API response, invalid API key and unexpected
  errors when fetching per device, all sites already set up, unknown uplink device, radio bands
  are only created once (coverage 97.1 % → 98.0 % on all three tested Home Assistant versions)

## 0.1.0

First release of the Home Assistant integration for UniFi Network through the official UniFi
Network API (version 10.3.58, authentication with an API key).

### Setup
- Setup in the UI: host, port, API key, SSL verification; selection of the site (one entry per site)
- Reconfigure (host, port, API key, SSL) and reauthentication when the API key is invalid
- Options: update intervals for devices/clients and device statistics/details, track clients on/off

### Entities
- **Site:** connected clients in total, wired, wireless, VPN and guests; number of adopted devices
- **Per device:** state, firmware update available, CPU and memory utilization, uplink rates,
  last restart, IP address, connected clients, uplink device, last provisioned, firmware version,
  load average, *Restart* button
- **Per radio band** (access points): channel, channel width, Wi-Fi standard, TX retries
- **Per port:** link, speed, maximum speed, connector type; PoE ports also PoE state, PoE details
  and the *PoE power cycle* button
- **Clients:** device trackers for wired and wireless clients (disabled by default)

### Other
- Device statistics and ports are loaded in the background after startup
- The last restart is derived from the heartbeat and restored across restarts of Home Assistant
  (no jumps without a real device restart)
- Newly adopted devices get their entities without a restart
- Own integration logo and entity icons
- Diagnostics export with redacted API key and host
- Texts in German and English
- GitHub Actions: tests (pytest, ruff) and the hassfest and HACS checks
- Categories in the manifest (`computers_network.routers_network`,
  `presence_location.network_presence`) so that the HACS check no longer warns
