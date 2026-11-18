"""Diagnostics support for UniFi Network Extended."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import HomeAssistant

from . import UnifiNetworkExtendedConfigEntry

# Never expose the API key or the host in downloaded diagnostics.
TO_REDACT = {CONF_API_KEY, CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: UnifiNetworkExtendedConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return {"entry": async_redact_data(entry.as_dict(), TO_REDACT)}
