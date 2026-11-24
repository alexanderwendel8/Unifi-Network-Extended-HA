"""Tests for setting up and unloading a config entry."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_network_extended.api import (
    UnifiCannotConnect,
    UnifiDeviceStatistics,
    UnifiInvalidAuth,
)
from custom_components.unifi_network_extended.const import (
    CONF_STATISTICS_INTERVAL,
    CONF_TRACK_CLIENTS,
    DOMAIN,
)

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


@pytest.mark.parametrize("mock", ["statistics", "details"])
async def test_device_data_invalid_auth_starts_reauth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    mock: str,
) -> None:
    """An invalid API key in a per-device request starts the reauth flow."""
    mock_api[mock].side_effect = UnifiInvalidAuth
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert config_entry.state is ConfigEntryState.LOADED
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_device_data_unexpected_error(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected errors are not mistaken for a single failing device."""
    mock_api["devices"].return_value = [GATEWAY, replace(ACCESS_POINT, state="ONLINE")]

    async def statistics(site_id: str, device_id: str) -> UnifiDeviceStatistics:
        if device_id == ACCESS_POINT.id:
            raise RuntimeError("boom")
        return GATEWAY_STATS

    mock_api["statistics"].side_effect = statistics
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    coordinator = config_entry.runtime_data.statistics_coordinator
    assert not coordinator.last_update_success
    assert "boom" in caplog.text
    assert hass.states.get("sensor.gateway_cpu_utilization").state == "unavailable"


async def _count_setups(
    hass: HomeAssistant, mock_api: dict[str, AsyncMock], before: int
) -> int:
    """Return how often the entry was set up since ``before`` device fetches.

    Every setup fetches the device list once (first refresh of the site
    coordinator); the next regular update is minutes away.
    """
    await hass.async_block_till_done(wait_background_tasks=True)
    return mock_api["devices"].await_count - before


def _tracker_entries(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> list[er.RegistryEntry]:
    """Return the device tracker entities of the entry."""
    return [
        entry
        for entry in er.async_entries_for_config_entry(
            er.async_get(hass), config_entry.entry_id
        )
        if entry.domain == "device_tracker"
    ]


# Home Assistant 2026.11 logs this when a flow reloads an entry that also has an
# update listener (``async_update_reload_and_abort``).
UPDATE_LISTENER_WARNING = "has an update listener"


async def test_reconfigure_reloads_once(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reconfigure reloads the entry exactly once."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    before = mock_api["devices"].await_count

    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.2",
            CONF_PORT: 443,
            CONF_API_KEY: "secret-key",
            CONF_VERIFY_SSL: True,
        },
    )
    assert result["reason"] == "reconfigure_successful"

    assert await _count_setups(hass, mock_api, before) == 1
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data[CONF_HOST] == "192.168.1.2"
    assert UPDATE_LISTENER_WARNING not in caplog.text


async def test_reauth_reloads_once(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A new API key reloads the entry exactly once."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    before = mock_api["devices"].await_count

    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    assert result["reason"] == "reauth_successful"

    assert await _count_setups(hass, mock_api, before) == 1
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data[CONF_API_KEY] == "new-key"
    assert UPDATE_LISTENER_WARNING not in caplog.text


async def test_options_change_reloads_once(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Changed options reload the entry once and apply at once; unchanged do not."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    before = mock_api["devices"].await_count

    options = {
        CONF_SCAN_INTERVAL: 60,
        CONF_STATISTICS_INTERVAL: 120,
        CONF_TRACK_CLIENTS: False,
    }
    assert _tracker_entries(hass, config_entry)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], options)
    assert await _count_setups(hass, mock_api, before) == 1
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.site_coordinator.update_interval == timedelta(
        seconds=60
    )
    assert not _tracker_entries(hass, config_entry)

    # Saving the same options again does not reload.
    before = mock_api["devices"].await_count
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], options)
    assert await _count_setups(hass, mock_api, before) == 0
