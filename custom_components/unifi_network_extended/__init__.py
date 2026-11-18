"""The UniFi Network Extended integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)

from .api import (
    UnifiApiClient,
    UnifiApiError,
    UnifiInvalidAuth,
    UnifiSite,
    async_create_api_client,
)
from .const import CONF_SITE_ID

# Add platforms here once entities are implemented, e.g. Platform.SENSOR.
PLATFORMS: list[Platform] = []


@dataclass(slots=True)
class UnifiRuntimeData:
    """Data kept in memory while the config entry is loaded."""

    client: UnifiApiClient
    site: UnifiSite


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

    entry.runtime_data = UnifiRuntimeData(client=client, site=site)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: UnifiNetworkExtendedConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
