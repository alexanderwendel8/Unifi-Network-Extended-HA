"""Tests for sensors, binary sensors and device trackers."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import (
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.unifi_network_extended.api import UnifiCannotConnect
from custom_components.unifi_network_extended.const import (
    CONF_TRACK_CLIENTS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STATISTICS_INTERVAL,
    DOMAIN,
)

from .conftest import ACCESS_POINT, GATEWAY, NAS, PHONE, SITE, VPN_USER


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, unique_id: str, domain: str = "sensor") -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id, unique_id
    return hass.states.get(entity_id).state


async def test_site_sensors(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Client and device counts of the site."""
    await _setup(hass, config_entry)

    assert _state(hass, f"{SITE.id}_clients") == "3"
    assert _state(hass, f"{SITE.id}_clients_wired") == "1"
    assert _state(hass, f"{SITE.id}_clients_wireless") == "1"
    assert _state(hass, f"{SITE.id}_devices") == "2"
    assert hass.states.get("sensor.default_connected_clients").state == "3"


async def test_device_sensors(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Device overview and statistics sensors."""
    await _setup(hass, config_entry)

    assert _state(hass, "dev-gw_state") == "online"
    assert _state(hass, "dev-ap_state") == "offline"
    assert _state(hass, "dev-gw_ip_address") == "192.168.1.1"
    assert _state(hass, "dev-gw_cpu_utilization") == "12.5"
    assert _state(hass, "dev-gw_memory_utilization") == "40.0"
    assert float(_state(hass, "dev-gw_uplink_rx_rate")) == 50.0  # Mbit/s
    assert _state(hass, "dev-gw_uptime") != STATE_UNAVAILABLE
    # No statistics for offline devices.
    assert _state(hass, "dev-ap_cpu_utilization") == STATE_UNAVAILABLE
    assert hass.states.get("sensor.gateway_cpu_utilization").state == "12.5"

    assert _state(hass, "dev-gw_firmware_update", "binary_sensor") == STATE_ON
    assert _state(hass, "dev-ap_firmware_update", "binary_sensor") == STATE_OFF


async def test_device_registry(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """UniFi devices are registered below the site device."""
    await _setup(hass, config_entry)
    registry = dr.async_get(hass)

    site = registry.async_get_device(identifiers={(DOMAIN, SITE.id)})
    gateway = registry.async_get_device(identifiers={(DOMAIN, GATEWAY.id)})
    assert site.name == "Default"
    assert gateway.model == "UCG Ultra"
    assert gateway.sw_version == "4.1.13"
    assert gateway.via_device_id == site.id
    assert (dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:00:00:01") in gateway.connections


def _register_known_devices(
    hass: HomeAssistant, entry: MockConfigEntry, *macs: str
) -> None:
    """Create devices with the given MACs (e.g. from another integration).

    Home Assistant only enables trackers by default for MACs that belong
    to a known device.
    """
    registry = dr.async_get(hass)
    for mac in macs:
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            connections={(dr.CONNECTION_NETWORK_MAC, mac.lower())},
        )


async def test_unknown_client_tracker_disabled_by_default(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Trackers of clients without a known device are created disabled."""
    await _setup(hass, config_entry)

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "device_tracker", DOMAIN, f"{SITE.id}_{PHONE.mac_address.lower()}"
    )
    disabled_by = registry.async_get(entity_id).disabled_by
    assert disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_client_trackers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Wired and wireless clients are tracked, VPN clients are not."""
    _register_known_devices(
        hass, config_entry, PHONE.mac_address, NAS.mac_address, "11:22:33:44:55:88"
    )
    await _setup(hass, config_entry)

    phone_uid = f"{SITE.id}_{PHONE.mac_address.lower()}"
    nas_uid = f"{SITE.id}_{NAS.mac_address.lower()}"
    assert _state(hass, phone_uid, "device_tracker") == STATE_HOME
    assert _state(hass, nas_uid, "device_tracker") == STATE_HOME
    trackers = [
        e
        for e in er.async_entries_for_config_entry(
            er.async_get(hass), config_entry.entry_id
        )
        if e.domain == "device_tracker"
    ]
    assert len(trackers) == 2
    assert VPN_USER.name not in [e.original_name for e in trackers]

    # Phone disconnects, a new client appears.
    laptop = replace(
        PHONE, id="client-laptop", name="Laptop", mac_address="11:22:33:44:55:88"
    )
    mock_api["clients"].return_value = [NAS, laptop]
    freezer.tick(timedelta(seconds=DEFAULT_SCAN_INTERVAL))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert _state(hass, phone_uid, "device_tracker") == STATE_NOT_HOME
    assert _state(hass, f"{SITE.id}_11:22:33:44:55:88", "device_tracker") == STATE_HOME


async def test_trackers_restored_after_reload(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Known clients keep their tracker (not_home) after a restart."""
    _register_known_devices(hass, config_entry, PHONE.mac_address)
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)

    mock_api["clients"].return_value = [NAS]
    await _setup(hass, config_entry)

    phone_uid = f"{SITE.id}_{PHONE.mac_address.lower()}"
    assert _state(hass, phone_uid, "device_tracker") == STATE_NOT_HOME


async def test_disable_client_tracking_removes_trackers(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Switching tracking off removes existing trackers."""
    await _setup(hass, config_entry)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_TRACK_CLIENTS: False}
    )
    await hass.async_block_till_done()

    entries = er.async_entries_for_config_entry(
        er.async_get(hass), config_entry.entry_id
    )
    assert not [e for e in entries if e.domain == "device_tracker"]


async def test_entities_unavailable_on_update_failure(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Entities become unavailable when polling fails."""
    await _setup(hass, config_entry)

    mock_api["devices"].side_effect = UnifiCannotConnect
    mock_api["statistics"].side_effect = UnifiCannotConnect
    freezer.tick(timedelta(seconds=DEFAULT_STATISTICS_INTERVAL))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert _state(hass, "dev-gw_state") == STATE_UNAVAILABLE
    assert _state(hass, "dev-gw_cpu_utilization") == STATE_UNAVAILABLE


async def test_new_device_is_added(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Devices adopted later get entities without a reload."""
    mock_api["devices"].return_value = [GATEWAY]
    await _setup(hass, config_entry)
    assert (
        er.async_get(hass).async_get_entity_id("sensor", DOMAIN, "dev-ap_state") is None
    )

    mock_api["devices"].return_value = [GATEWAY, ACCESS_POINT]
    freezer.tick(timedelta(seconds=DEFAULT_SCAN_INTERVAL))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert _state(hass, "dev-ap_state") == "offline"


async def test_device_info_uses_via_device_id_when_supported(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Newer Home Assistant versions get the parent's registry ID."""
    from custom_components.unifi_network_extended import entity

    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data.site_coordinator
    site_device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, SITE.id)})
    assert coordinator.site_device_id == site_device.id

    monkeypatch.setattr(entity, "SUPPORTS_VIA_DEVICE_ID", True)
    info = entity.unifi_device_info(coordinator, GATEWAY)
    assert info["via_device_id"] == site_device.id
    assert "via_device" not in info

    monkeypatch.setattr(entity, "SUPPORTS_VIA_DEVICE_ID", False)
    info = entity.unifi_device_info(coordinator, GATEWAY)
    assert info["via_device"] == (DOMAIN, SITE.id)
    assert "via_device_id" not in info


async def test_tracker_describes_client_device(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Trackers carry the client's MAC address as device connection."""
    from custom_components.unifi_network_extended.device_tracker import (
        UnifiClientTracker,
    )

    await _setup(hass, config_entry)
    tracker = UnifiClientTracker(
        config_entry.runtime_data.site_coordinator,
        PHONE.mac_address.lower(),
        PHONE.name,
    )
    assert tracker._attr_device_info["connections"] == {
        (dr.CONNECTION_NETWORK_MAC, PHONE.mac_address.lower())
    }
    assert tracker._attr_device_info["name"] == "Phone"
