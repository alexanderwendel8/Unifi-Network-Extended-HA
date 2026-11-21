"""Tests for port entities (link, speed, PoE) and the PoE power-cycle button."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.unifi_network_extended.api import (
    UnifiCannotConnect,
    UnifiDeviceDetails,
    UnifiInvalidAuth,
    UnifiPort,
)
from custom_components.unifi_network_extended.const import (
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STATISTICS_INTERVAL,
    DOMAIN,
)

from .conftest import (
    ACCESS_POINT,
    ACCESS_POINT_DETAILS,
    GATEWAY,
    GATEWAY_DETAILS,
    SITE,
)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let the device list update first, then the per-device port data."""
    for seconds in (DEFAULT_SCAN_INTERVAL, DEFAULT_STATISTICS_INTERVAL):
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)


def _entity_id(hass: HomeAssistant, domain: str, port: int, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{GATEWAY.id}_port{port}_{key}"
    )


def _state(hass: HomeAssistant, domain: str, port: int, key: str) -> str:
    entity_id = _entity_id(hass, domain, port, key)
    assert entity_id, (domain, port, key)
    return hass.states.get(entity_id).state


async def _enable(
    hass: HomeAssistant, entry: MockConfigEntry, *entities: tuple[str, int, str]
) -> None:
    """Enable entities that are disabled by default and reload."""
    registry = er.async_get(hass)
    for domain, port, key in entities:
        registry.async_update_entity(
            _entity_id(hass, domain, port, key), disabled_by=None
        )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_details_only_requested_for_online_devices(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """The access point is offline, so only the gateway details are fetched."""
    await _setup(hass, config_entry)
    mock_api["details"].assert_awaited_once_with(SITE.id, GATEWAY.id)


async def test_port_link_and_speed(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Link state and current speed of every port."""
    await _setup(hass, config_entry)

    assert _state(hass, "binary_sensor", 1, "link") == STATE_ON
    assert _state(hass, "binary_sensor", 2, "link") == STATE_OFF
    assert _state(hass, "sensor", 1, "link_speed") == "1000"
    assert _state(hass, "sensor", 2, "link_speed") == "0"
    assert _state(hass, "sensor", 3, "link_speed") == "10000"
    assert hass.states.get("binary_sensor.gateway_port_1_link").state == STATE_ON
    assert hass.states.get("sensor.gateway_port_1_link_speed").state == "1000"


async def test_port_diagnostics_disabled_by_default(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Diagnostic port entities exist but are disabled; they work when enabled."""
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    for domain, key in (
        ("sensor", "max_speed"),
        ("sensor", "connector"),
        ("sensor", "poe_standard"),
        ("sensor", "poe_type"),
        ("binary_sensor", "poe_enabled"),
    ):
        entry = registry.async_get(_entity_id(hass, domain, 1, key))
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION, key

    await _enable(
        hass,
        config_entry,
        ("sensor", 3, "max_speed"),
        ("sensor", 3, "connector"),
        ("sensor", 1, "poe_standard"),
        ("sensor", 1, "poe_type"),
        ("binary_sensor", 2, "poe_enabled"),
    )
    assert _state(hass, "sensor", 3, "max_speed") == "10000"
    assert _state(hass, "sensor", 3, "connector") == "sfpplus"
    assert _state(hass, "sensor", 1, "poe_standard") == "802.3at"
    assert _state(hass, "sensor", 1, "poe_type") == "2"
    assert _state(hass, "binary_sensor", 2, "poe_enabled") == STATE_OFF


async def test_poe_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """PoE entities only exist for PoE ports, enabled where PoE is switched on."""
    await _setup(hass, config_entry)
    registry = er.async_get(hass)

    assert _state(hass, "sensor", 1, "poe_state") == "up"
    assert hass.states.get("sensor.gateway_port_1_poe").state == "up"
    # PoE switched off on port 2: entities exist but are disabled.
    for domain, key in (("sensor", "poe_state"), ("button", "poe_power_cycle")):
        entry = registry.async_get(_entity_id(hass, domain, 2, key))
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    # Port 3 has no PoE at all.
    assert _entity_id(hass, "sensor", 3, "poe_state") is None
    assert _entity_id(hass, "button", 3, "poe_power_cycle") is None
    assert _entity_id(hass, "binary_sensor", 3, "poe_enabled") is None


async def test_power_cycle_button(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Pressing the button power-cycles the port and refreshes the ports."""
    await _setup(hass, config_entry)
    entity_id = _entity_id(hass, "button", 1, "poe_power_cycle")
    assert entity_id == "button.gateway_port_1_poe_power_cycle"
    calls = mock_api["details"].await_count

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    mock_api["power_cycle"].assert_awaited_once_with(SITE.id, GATEWAY.id, 1)
    assert mock_api["details"].await_count > calls


async def test_power_cycle_button_unavailable_without_poe(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """The button is unavailable while PoE is disabled on the port."""
    await _setup(hass, config_entry)
    await _enable(hass, config_entry, ("button", 2, "poe_power_cycle"))
    assert _state(hass, "button", 2, "poe_power_cycle") == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("side_effect", "translation_key"),
    [(UnifiCannotConnect, "power_cycle_failed"), (UnifiInvalidAuth, "invalid_auth")],
)
async def test_power_cycle_button_errors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    side_effect: type[Exception],
    translation_key: str,
) -> None:
    """Errors are shown to the user, an invalid key starts reauth."""
    await _setup(hass, config_entry)
    mock_api["power_cycle"].side_effect = side_effect

    with pytest.raises(HomeAssistantError) as exc_info:
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: _entity_id(hass, "button", 1, "poe_power_cycle")},
            blocking=True,
        )
    assert exc_info.value.translation_key == translation_key
    if side_effect is UnifiInvalidAuth:
        flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    else:
        assert exc_info.value.translation_placeholders == {
            "port": "1",
            "device": "Gateway",
            "error": "",
        }


async def test_ports_unavailable_when_device_goes_offline(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Port data of an offline device is unavailable."""
    await _setup(hass, config_entry)

    mock_api["devices"].return_value = [replace(GATEWAY, state="OFFLINE")]
    await _poll(hass, freezer)

    assert _state(hass, "binary_sensor", 1, "link") == STATE_UNAVAILABLE
    assert _state(hass, "button", 1, "poe_power_cycle") == STATE_UNAVAILABLE


async def test_new_device_ports_are_added(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A switch that comes online later gets its port entities."""
    await _setup(hass, config_entry)
    switch = replace(
        ACCESS_POINT,
        id="dev-sw",
        name="Switch",
        state="ONLINE",
        interfaces=frozenset({"ports"}),
    )
    switch_ports = {
        5: UnifiPort(
            idx=5,
            state="UP",
            connector="RJ45",
            max_speed_mbps=1000,
            speed_mbps=100,
            poe=None,
        )
    }
    mock_api["devices"].return_value = [GATEWAY, switch]
    switch_details = replace(ACCESS_POINT_DETAILS, ports=switch_ports)

    async def details(site_id: str, device_id: str) -> UnifiDeviceDetails:
        return switch_details if device_id == "dev-sw" else GATEWAY_DETAILS

    mock_api["details"].side_effect = details
    await _poll(hass, freezer)

    assert hass.states.get("binary_sensor.switch_port_5_link").state == STATE_ON
    assert hass.states.get("sensor.switch_port_5_link_speed").state == "100"
