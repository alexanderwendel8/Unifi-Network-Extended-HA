"""Tests for setting up and unloading a config entry."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_network_extended.api import (
    UnifiCannotConnect,
    UnifiDeviceStatistics,
    UnifiInvalidAuth,
)
from custom_components.unifi_network_extended.const import DOMAIN

from .conftest import ACCESS_POINT, GATEWAY, GATEWAY_STATS, SITE


async def test_setup_and_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """The entry loads with the configured site and unloads again."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.site == SITE
    await hass.async_block_till_done(wait_background_tasks=True)
    # Statistics are only requested for online devices.
    mock_api["statistics"].assert_awaited_once_with(SITE.id, "dev-gw")

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    ("mock", "kwargs", "state"),
    [
        ("sites", {"side_effect": UnifiCannotConnect}, ConfigEntryState.SETUP_RETRY),
        ("sites", {"side_effect": UnifiInvalidAuth}, ConfigEntryState.SETUP_ERROR),
        ("sites", {"return_value": []}, ConfigEntryState.SETUP_ERROR),
        ("devices", {"side_effect": UnifiCannotConnect}, ConfigEntryState.SETUP_RETRY),
        ("clients", {"side_effect": UnifiInvalidAuth}, ConfigEntryState.SETUP_ERROR),
        # Statistics and ports load in the background and do not block the setup.
        ("statistics", {"side_effect": UnifiCannotConnect}, ConfigEntryState.LOADED),
        ("details", {"side_effect": UnifiCannotConnect}, ConfigEntryState.LOADED),
    ],
)
async def test_setup_failures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    mock: str,
    kwargs: dict,
    state: ConfigEntryState,
) -> None:
    """Connection errors retry; invalid keys and missing sites do not."""
    mock_api[mock].configure_mock(**kwargs)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is state


async def test_invalid_key_starts_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """An invalid API key starts the reauth flow."""
    mock_api["sites"].side_effect = UnifiInvalidAuth
    await hass.config_entries.async_setup(config_entry.entry_id)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_statistics_partial_failure(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """A single failing device does not fail the statistics update."""
    mock_api["devices"].return_value = [GATEWAY, replace(ACCESS_POINT, state="ONLINE")]

    async def statistics(site_id: str, device_id: str) -> UnifiDeviceStatistics:
        if device_id == ACCESS_POINT.id:
            raise UnifiCannotConnect
        return GATEWAY_STATS

    mock_api["statistics"].side_effect = statistics
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert config_entry.runtime_data.statistics_coordinator.data == {
        GATEWAY.id: GATEWAY_STATS
    }


async def test_setup_does_not_wait_for_device_data(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Statistics and ports are loaded in parallel after the setup finished."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_statistics(site_id: str, device_id: str) -> UnifiDeviceStatistics:
        started.set()
        await release.wait()
        return GATEWAY_STATS

    mock_api["statistics"].side_effect = slow_statistics
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.LOADED
    await started.wait()
    # Details were fetched while the statistics were still pending.
    mock_api["details"].assert_awaited_once()
    assert config_entry.runtime_data.statistics_coordinator.data == {}
    assert hass.states.get("sensor.gateway_cpu_utilization").state == "unavailable"

    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("sensor.gateway_cpu_utilization").state == "12.5"
