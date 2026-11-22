"""Tests for sensors, binary sensors and device trackers."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import (
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from custom_components.unifi_network_extended.api import UnifiCannotConnect
from custom_components.unifi_network_extended.const import (
    CONF_TRACK_CLIENTS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STATISTICS_INTERVAL,
    DOMAIN,
)

from .conftest import ACCESS_POINT, GATEWAY, GATEWAY_STATS, NAS, PHONE, SITE, VPN_USER


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


def _get_device(
    hass: HomeAssistant, entry: MockConfigEntry, device_id: str
) -> dr.DeviceEntry | None:
    """Look up a device of the integration by identifier.

    Newer Home Assistant versions replaced async_get_device (identifiers are no
    longer unique across config entries) with async_get_device_by_identifier.
    """
    registry = dr.async_get(hass)
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier(
            (DOMAIN, device_id), entry.entry_id
        )
    return registry.async_get_device(identifiers={(DOMAIN, device_id)})


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

    site = _get_device(hass, config_entry, SITE.id)
    gateway = _get_device(hass, config_entry, GATEWAY.id)
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
    site_device = _get_device(hass, config_entry, SITE.id)
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


async def test_device_clients_uplink_and_provisioning(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Clients per device, uplink device and last provisioning."""
    await _setup(hass, config_entry)
    await hass.async_block_till_done(wait_background_tasks=True)

    # PHONE is connected to the access point, NAS to the gateway, VPN to nothing.
    assert _state(hass, f"{GATEWAY.id}_clients") == "1"
    assert _state(hass, f"{ACCESS_POINT.id}_clients") == "1"
    assert hass.states.get("sensor.gateway_connected_clients").state == "1"

    # The gateway has no uplink; the offline access point has no details yet.
    assert _state(hass, f"{GATEWAY.id}_uplink_device") == "unknown"
    assert _state(hass, f"{ACCESS_POINT.id}_uplink_device") == STATE_UNAVAILABLE
    assert _state(hass, f"{GATEWAY.id}_last_provisioned") == "2026-11-01T12:00:00+00:00"

    # The access point comes online and reports the gateway as uplink.
    mock_api["devices"].return_value = [GATEWAY, replace(ACCESS_POINT, state="ONLINE")]
    for seconds in (DEFAULT_SCAN_INTERVAL, DEFAULT_STATISTICS_INTERVAL):
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert _state(hass, f"{ACCESS_POINT.id}_uplink_device") == "Gateway"
    assert hass.states.get("sensor.access_point_uplink_device").state == "Gateway"


async def test_radio_sensors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Each radio band of an access point gets its own sensors."""
    mock_api["devices"].return_value = [GATEWAY, replace(ACCESS_POINT, state="ONLINE")]
    await _setup(hass, config_entry)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get("sensor.access_point_2_4_ghz_channel").state == "6"
    assert hass.states.get("sensor.access_point_5_ghz_channel").state == "36"
    assert hass.states.get("sensor.access_point_5_ghz_channel_width").state == "160"
    assert (
        hass.states.get("sensor.access_point_5_ghz_wi_fi_standard").state == "802.11be"
    )
    assert hass.states.get("sensor.access_point_2_4_ghz_tx_retries").state == "12.5"
    assert hass.states.get("sensor.access_point_5_ghz_tx_retries").state == "3.2"
    assert _state(hass, f"{ACCESS_POINT.id}_radio_2_4_channel") == "6"
    # The gateway has no radios.
    registry = er.async_get(hass)
    assert not [
        e
        for e in er.async_entries_for_config_entry(registry, config_entry.entry_id)
        if e.unique_id.startswith(f"{GATEWAY.id}_radio")
    ]

    # The access point goes offline: radio data becomes unavailable.
    mock_api["devices"].return_value = [GATEWAY, ACCESS_POINT]
    for seconds in (DEFAULT_SCAN_INTERVAL, DEFAULT_STATISTICS_INTERVAL):
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert (
        hass.states.get("sensor.access_point_5_ghz_channel").state == STATE_UNAVAILABLE
    )
    assert (
        hass.states.get("sensor.access_point_5_ghz_tx_retries").state
        == STATE_UNAVAILABLE
    )


async def test_last_restart_is_stable_across_reloads(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """The boot time is derived from the heartbeat, not from the current time."""
    heartbeat = datetime(2026, 11, 22, 10, 0, 0, tzinfo=UTC)
    stats = replace(GATEWAY_STATS, uptime_sec=3600, last_heartbeat_at=heartbeat)
    mock_api["statistics"].side_effect = None
    mock_api["statistics"].return_value = stats
    freezer.move_to(datetime(2026, 11, 22, 10, 0, 37, tzinfo=UTC))
    await _setup(hass, config_entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _state(hass, "dev-gw_uptime") == "2026-11-22T09:00:00+00:00"

    # Reloading later (e.g. after a Home Assistant restart) keeps the value.
    freezer.move_to(datetime(2026, 11, 22, 10, 3, 11, tzinfo=UTC))
    mock_api["statistics"].return_value = replace(
        stats, uptime_sec=3600 + 180, last_heartbeat_at=heartbeat + timedelta(minutes=3)
    )
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _state(hass, "dev-gw_uptime") == "2026-11-22T09:00:00+00:00"

    # A real reboot moves the value.
    mock_api["statistics"].return_value = replace(
        stats, uptime_sec=60, last_heartbeat_at=heartbeat + timedelta(minutes=4)
    )
    for seconds in (DEFAULT_SCAN_INTERVAL, DEFAULT_STATISTICS_INTERVAL):
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert _state(hass, "dev-gw_uptime") == "2026-11-22T10:03:00+00:00"


async def test_last_restart_is_restored(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A restored boot time is kept when the new value is only slightly off."""
    entity_id = "sensor.gateway_last_restart"
    restored = datetime(2026, 11, 22, 9, 0, 40, tzinfo=UTC)
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(entity_id, restored.isoformat()),
                {
                    "native_value": {
                        "__type": str(datetime),
                        "isoformat": restored.isoformat(),
                    },
                    "native_unit_of_measurement": None,
                },
            )
        ],
    )
    # Restore entries need an existing registry entry with the same entity_id.
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{GATEWAY.id}_uptime",
        config_entry=config_entry,
        suggested_object_id="gateway_last_restart",
    )

    # The device reports a boot time 40 seconds earlier: keep the restored value.
    heartbeat = datetime(2026, 11, 22, 10, 0, 0, tzinfo=UTC)
    mock_api["statistics"].side_effect = None
    mock_api["statistics"].return_value = replace(
        GATEWAY_STATS, uptime_sec=3600, last_heartbeat_at=heartbeat
    )
    freezer.move_to(heartbeat + timedelta(seconds=5))
    await _setup(hass, config_entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(entity_id).state == "2026-11-22T09:00:40+00:00"

    # A real reboot (boot time far away) replaces it.
    mock_api["statistics"].return_value = replace(
        GATEWAY_STATS, uptime_sec=30, last_heartbeat_at=heartbeat
    )
    for seconds in (DEFAULT_SCAN_INTERVAL, DEFAULT_STATISTICS_INTERVAL):
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(entity_id).state == "2026-11-22T09:59:30+00:00"
