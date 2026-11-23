"""The UniFi Network Extended integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import device_registry as dr

from .api import (
    UnifiApiClient,
    UnifiApiError,
    UnifiInvalidAuth,
    UnifiSite,
    async_create_api_client,
)
from .const import (
    CONF_SITE_ID,
    CONF_STATISTICS_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STATISTICS_INTERVAL,
    DOMAIN,
)
from .coordinator import (
    UnifiApplicationInfoCoordinator,
    UnifiDeviceDetailsCoordinator,
    UnifiSiteCoordinator,
    UnifiStatisticsCoordinator,
)
from .entity import MANUFACTURER, SITE_MODEL

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
]


@dataclass(slots=True)
class UnifiRuntimeData:
    """Data kept in memory while the config entry is loaded."""

    client: UnifiApiClient
    site: UnifiSite
    site_coordinator: UnifiSiteCoordinator
    statistics_coordinator: UnifiStatisticsCoordinator
    details_coordinator: UnifiDeviceDetailsCoordinator
    application_info_coordinator: UnifiApplicationInfoCoordinator


type UnifiNetworkExtendedConfigEntry = ConfigEntry[UnifiRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: UnifiNetworkExtendedConfigEntry
) -> bool:
    """Set up UniFi Network Extended from a config entry."""
    client = async_create_api_client(hass, entry.data)

    try:
        sites = await client.async_get_sites()
    except UnifiInvalidAuth as err:
        # Triggers the reauth flow in the UI.
        raise ConfigEntryAuthFailed("Invalid API key") from err
    except UnifiApiError as err:
        # Includes UnifiCannotConnect. Home Assistant retries the setup automatically.
        raise ConfigEntryNotReady(
            f"Cannot connect to {entry.data[CONF_HOST]}: {err}"
        ) from err

    site = next((site for site in sites if site.id == entry.data[CONF_SITE_ID]), None)
    if site is None:
        # Not retried: the site was deleted or the API key has no access to it.
        raise ConfigEntryError(f"Site {entry.title} no longer exists")

    # Version of the Network application, shown as software version of the site
    # device. Not required for the setup: a failure is logged, the version stays
    # unknown until the next hourly check. An invalid API key starts the reauth
    # flow (handled by the coordinator).
    application_info_coordinator = UnifiApplicationInfoCoordinator(
        hass, entry, client, site
    )
    await application_info_coordinator.async_refresh()

    # Register the site device first, UniFi devices reference it as parent.
    # An unknown version is not passed, so a version stored earlier is kept.
    device_registry = dr.async_get(hass)
    site_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, site.id)},
        name=site.name,
        manufacturer=MANUFACTURER,
        model=SITE_MODEL,
        entry_type=dr.DeviceEntryType.SERVICE,
        **(
            {"sw_version": application_info_coordinator.data}
            if application_info_coordinator.data
            else {}
        ),
    )

    @callback
    def _async_update_site_device_version() -> None:
        """Store a changed application version on the site device."""
        version = application_info_coordinator.data
        device = device_registry.async_get(site_device.id)
        if version and device is not None and device.sw_version != version:
            device_registry.async_update_device(site_device.id, sw_version=version)

    # Also keeps the hourly check running if the version sensor is disabled.
    entry.async_on_unload(
        application_info_coordinator.async_add_listener(
            _async_update_site_device_version
        )
    )

    site_coordinator = UnifiSiteCoordinator(
        hass,
        entry,
        client,
        site,
        site_device.id,
        entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    await site_coordinator.async_config_entry_first_refresh()

    statistics_coordinator = UnifiStatisticsCoordinator(
        hass,
        entry,
        site_coordinator,
        entry.options.get(CONF_STATISTICS_INTERVAL, DEFAULT_STATISTICS_INTERVAL),
    )
    # Device details (ports, uplink, provisioning): one request per device.
    details_coordinator = UnifiDeviceDetailsCoordinator(
        hass,
        entry,
        site_coordinator,
        entry.options.get(CONF_STATISTICS_INTERVAL, DEFAULT_STATISTICS_INTERVAL),
    )

    entry.runtime_data = UnifiRuntimeData(
        client=client,
        site=site,
        site_coordinator=site_coordinator,
        statistics_coordinator=statistics_coordinator,
        details_coordinator=details_coordinator,
        application_info_coordinator=application_info_coordinator,
    )

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    # Home Assistant only applies device_info when an entity is added. Keep
    # firmware version and name of the UniFi devices up to date afterwards.
    entry.async_on_unload(
        site_coordinator.async_add_listener(
            lambda: _async_update_device_registry(hass, entry, site_coordinator)
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Statistics and ports need one request per device. Load them in parallel in
    # the background instead of delaying the setup: their entities show up as
    # unavailable (statistics) or are added (ports) once the data has arrived.
    entry.async_create_background_task(
        hass,
        _async_load_device_data(statistics_coordinator, details_coordinator),
        f"{DOMAIN} {site.name} initial device data",
    )
    return True


def _async_get_registry_device(
    registry: dr.DeviceRegistry, entry_id: str, identifier: tuple[str, str]
) -> dr.DeviceEntry | None:
    """Look up a device of the config entry by identifier.

    Home Assistant 2026.11 deprecated async_get_device (identifiers are no longer
    unique across config entries) in favor of async_get_device_by_identifier.
    """
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier(identifier, entry_id)
    return registry.async_get_device(identifiers={identifier})


@callback
def _async_update_device_registry(
    hass: HomeAssistant,
    entry: UnifiNetworkExtendedConfigEntry,
    coordinator: UnifiSiteCoordinator,
) -> None:
    """Write changed firmware versions and names of UniFi devices to the registry.

    Only ``name`` is updated, a name set by the user (``name_by_user``) is kept.
    Devices without registry entry (no entities yet) are skipped.
    """
    if coordinator.data is None:
        return
    registry = dr.async_get(hass)
    for device in coordinator.data.devices.values():
        device_entry = _async_get_registry_device(
            registry, entry.entry_id, (DOMAIN, device.id)
        )
        if device_entry is None:
            continue
        changes: dict[str, str | None] = {}
        if device_entry.sw_version != (sw_version := device.firmware_version or None):
            changes["sw_version"] = sw_version
        if device.name and device_entry.name != device.name:
            changes["name"] = device.name
        if changes:
            registry.async_update_device(device_entry.id, **changes)


async def _async_load_device_data(
    statistics_coordinator: UnifiStatisticsCoordinator,
    details_coordinator: UnifiDeviceDetailsCoordinator,
) -> None:
    """Run the first refresh of the per-device coordinators in parallel.

    Errors are handled by the coordinators (logged, entities unavailable, reauth
    on an invalid API key) and retried at the next interval.
    """
    await asyncio.gather(
        statistics_coordinator.async_refresh(), details_coordinator.async_refresh()
    )


async def _async_options_updated(
    hass: HomeAssistant, entry: UnifiNetworkExtendedConfigEntry
) -> None:
    """Reload the entry when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: UnifiNetworkExtendedConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: UnifiNetworkExtendedConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow deleting a UniFi device in the UI once UniFi no longer reports it.

    The site device and devices still reported by UniFi (online or offline) can't
    be deleted. Devices without an identifier of this integration (e.g. clients
    created by device trackers) are not managed here and can't be deleted either.
    """
    unifi_ids = {
        identifier[1]
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN
    }
    if not unifi_ids or entry.runtime_data.site.id in unifi_ids:
        return False
    return not unifi_ids & set(entry.runtime_data.site_coordinator.data.devices)
