"""The UniFi Network Extended integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
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

    # Register the site device first, UniFi devices reference it as parent.
    site_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, site.id)},
        name=site.name,
        manufacturer=MANUFACTURER,
        model=SITE_MODEL,
        entry_type=dr.DeviceEntryType.SERVICE,
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
    )

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
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
