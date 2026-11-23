"""Tests for the version of the UniFi Network application (``GET /v1/info``)."""

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.unifi_network_extended.api import (
    UnifiApiError,
    UnifiCannotConnect,
    UnifiInvalidAuth,
)
from custom_components.unifi_network_extended.const import (
    APPLICATION_INFO_INTERVAL,
    DOMAIN,
)

from .conftest import APPLICATION_VERSION, SITE

UNIQUE_ID = f"{SITE.id}_network_version"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


def _site_device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    """Return the site device (lookup works on old and new Home Assistant)."""
    registry = dr.async_get(hass)
    if hasattr(registry, "async_get_device_by_identifier"):
        device = registry.async_get_device_by_identifier(
            (DOMAIN, SITE.id), entry.entry_id
        )
    else:
        device = registry.async_get_device(identifiers={(DOMAIN, SITE.id)})
    assert device is not None
    return device


def _sensor_entity_id(hass: HomeAssistant) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, UNIQUE_ID)
    assert entity_id
    return entity_id


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(seconds=APPLICATION_INFO_INTERVAL))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_version_on_site_device_and_sensor(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """After the setup the version is the site device's software version."""
    await _setup(hass, config_entry)

    assert _site_device(hass, config_entry).sw_version == APPLICATION_VERSION
    entity_id = _sensor_entity_id(hass)
    assert hass.states.get(entity_id).state == APPLICATION_VERSION
    assert entity_id == "sensor.default_unifi_network_version"

    entry = er.async_get(hass).async_get(entity_id)
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    assert entry.device_id == _site_device(hass, config_entry).id
    # Fetched once during the setup, not with every site poll.
    mock_api["application_version"].assert_awaited_once()


async def test_new_version_is_applied(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """An updated Network application shows up after the next hourly check."""
    await _setup(hass, config_entry)
    mock_api["application_version"].return_value = "10.4.1"

    await _tick(hass, freezer)

    assert mock_api["application_version"].await_count == 2
    assert _site_device(hass, config_entry).sw_version == "10.4.1"
    assert hass.states.get(_sensor_entity_id(hass)).state == "10.4.1"


async def test_version_checked_hourly_with_disabled_sensor(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """The site device is updated even if the user disabled the sensor."""
    await _setup(hass, config_entry)
    er.async_get(hass).async_update_entity(
        _sensor_entity_id(hass), disabled_by=er.RegistryEntryDisabler.USER
    )
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_api["application_version"].return_value = "10.4.1"

    await _tick(hass, freezer)

    assert _site_device(hass, config_entry).sw_version == "10.4.1"


@pytest.mark.parametrize("error", [UnifiCannotConnect, UnifiApiError])
async def test_version_error_does_not_block_setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
    error: type[Exception],
) -> None:
    """Without a version the entry still loads; the next check fills it in."""
    mock_api["application_version"].side_effect = error
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert _site_device(hass, config_entry).sw_version is None
    assert hass.states.get(_sensor_entity_id(hass)).state == STATE_UNAVAILABLE
    # Other site sensors work as usual.
    assert hass.states.get("sensor.default_connected_clients").state == "3"

    mock_api["application_version"].side_effect = None
    await _tick(hass, freezer)

    assert _site_device(hass, config_entry).sw_version == APPLICATION_VERSION
    assert hass.states.get(_sensor_entity_id(hass)).state == APPLICATION_VERSION


async def test_failed_check_keeps_known_version(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A failed check marks the sensor unavailable but keeps the device version."""
    await _setup(hass, config_entry)
    mock_api["application_version"].side_effect = UnifiCannotConnect

    await _tick(hass, freezer)

    assert hass.states.get(_sensor_entity_id(hass)).state == STATE_UNAVAILABLE
    assert _site_device(hass, config_entry).sw_version == APPLICATION_VERSION

    # A restart while the check fails keeps the stored version as well.
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert config_entry.state is ConfigEntryState.LOADED
    assert _site_device(hass, config_entry).sw_version == APPLICATION_VERSION


async def test_invalid_key_during_setup_starts_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """An invalid API key on the version check starts the reauth flow."""
    mock_api["application_version"].side_effect = UnifiInvalidAuth
    await _setup(hass, config_entry)

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_invalid_key_on_hourly_check_starts_reauth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """An API key revoked later starts the reauth flow at the next check."""
    await _setup(hass, config_entry)
    mock_api["application_version"].side_effect = UnifiInvalidAuth

    await _tick(hass, freezer)

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert SOURCE_REAUTH in {flow["context"]["source"] for flow in flows}
