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
    runtime = entry.runtime_data
    site_data = runtime.site_coordinator.data
    # Only counts and states; client names and addresses are personal data.
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "application": {
            "last_update_success": (
                runtime.application_info_coordinator.last_update_success
            ),
            "version": runtime.application_info_coordinator.data,
        },
        "site_coordinator": {
            "last_update_success": runtime.site_coordinator.last_update_success,
            "device_count": len(site_data.devices),
            "client_count": len(site_data.clients),
            "devices": [
                {
                    "model": device.model,
                    "state": device.state,
                    "firmware_version": device.firmware_version,
                    "firmware_updatable": device.firmware_updatable,
                    "features": sorted(device.features),
                }
                for device in site_data.devices.values()
            ],
        },
        "details_coordinator": {
            "last_update_success": runtime.details_coordinator.last_update_success,
            "device_count": len(runtime.details_coordinator.data),
            "port_count": sum(
                len(details.ports)
                for details in runtime.details_coordinator.data.values()
            ),
            "poe_port_count": sum(
                port.poe is not None
                for details in runtime.details_coordinator.data.values()
                for port in details.ports.values()
            ),
        },
        "statistics_coordinator": {
            "last_update_success": runtime.statistics_coordinator.last_update_success,
            "device_count": len(runtime.statistics_coordinator.data),
        },
    }
