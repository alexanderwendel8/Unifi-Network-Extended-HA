"""Tests for diagnostics."""

from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_network_extended.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redacts_secrets(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """API key, host and client details are not part of the diagnostics."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diagnostics["entry"]["data"]["api_key"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["host"] == "**REDACTED**"
    assert diagnostics["site_coordinator"]["client_count"] == 3
    text = str(diagnostics)
    for secret in ("secret-key", "192.168.1.1", "Phone", "11:22:33:44:55:66"):
        assert secret not in text
