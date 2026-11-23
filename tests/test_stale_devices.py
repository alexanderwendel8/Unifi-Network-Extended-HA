"""Tests for removing devices that UniFi no longer reports."""

from dataclasses import replace
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_network_extended import (
    async_remove_config_entry_device,
)
from custom_components.unifi_network_extended.api import UnifiCannotConnect
from custom_components.unifi_network_extended.const import DOMAIN

from .conftest import ACCESS_POINT, GATEWAY, SITE
from .test_entities import _get_device

CLIENT_MAC = "11:22:33:44:55:99"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _refresh(entry: MockConfigEntry, hass: HomeAssistant) -> None:
    """Run the next update of the site coordinator."""
    await entry.runtime_data.site_coordinator.async_refresh()
    await hass.async_block_till_done()


def _entity_ids(hass: HomeAssistant, unifi_device_id: str) -> set[str]:
    """Return the registered entities whose unique ID belongs to a UniFi device."""
    return {
        entry.entity_id
        for entry in er.async_get(hass).entities.values()
        if entry.platform == DOMAIN
        and entry.unique_id.startswith(f"{unifi_device_id}_")
    }


async def test_removed_device_is_deleted_with_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """A device missing from the device list is removed after the next update."""
    await _setup(hass, config_entry)
    gateway = _get_device(hass, config_entry, GATEWAY.id)
    assert gateway is not None
    gateway_entities = _entity_ids(hass, GATEWAY.id)
    # Device sensors, port entities and the restart button.
    assert "button.gateway_restart" in gateway_entities
    assert any("port_1" in entity_id for entity_id in gateway_entities)

    mock_api["devices"].return_value = [ACCESS_POINT]
    await _refresh(config_entry, hass)

    assert _get_device(hass, config_entry, GATEWAY.id) is None
    assert dr.async_get(hass).async_get(gateway.id) is None
    assert _entity_ids(hass, GATEWAY.id) == set()
    for entity_id in gateway_entities:
        assert hass.states.get(entity_id) is None
    # The offline access point and the site device are kept.
    assert _get_device(hass, config_entry, ACCESS_POINT.id) is not None
    assert _get_device(hass, config_entry, SITE.id) is not None


async def test_offline_device_is_kept(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Offline devices are still reported by UniFi and stay in the registry."""
    await _setup(hass, config_entry)
    assert ACCESS_POINT.state == "OFFLINE"
    ap_entities = _entity_ids(hass, ACCESS_POINT.id)
    assert ap_entities

    await _refresh(config_entry, hass)

    assert _get_device(hass, config_entry, ACCESS_POINT.id) is not None
    assert _entity_ids(hass, ACCESS_POINT.id) == ap_entities


async def test_device_with_invalid_data_is_kept(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """A device skipped for invalid data is still reported by UniFi and stays."""
    await _setup(hass, config_entry)
    gateway_entities = _entity_ids(hass, GATEWAY.id)

    async def _devices_with_invalid_gateway(
        site_id: str, *, skipped_ids: set[str] | None = None
    ) -> list:
        # The API client skips the gateway and reports its ID as skipped.
        if skipped_ids is not None:
            skipped_ids.add(GATEWAY.id)
        return [ACCESS_POINT]

    mock_api["devices"].side_effect = _devices_with_invalid_gateway
    await _refresh(config_entry, hass)

    assert _get_device(hass, config_entry, GATEWAY.id) is not None
    assert _entity_ids(hass, GATEWAY.id) == gateway_entities


async def test_failed_update_removes_nothing(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Nothing is removed while the device list can't be fetched."""
    await _setup(hass, config_entry)
    devices_before = dr.async_entries_for_config_entry(
        dr.async_get(hass), config_entry.entry_id
    )

    mock_api["devices"].side_effect = UnifiCannotConnect
    await _refresh(config_entry, hass)
    assert not config_entry.runtime_data.site_coordinator.last_update_success

    assert (
        dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
        == devices_before
    )
    assert _entity_ids(hass, GATEWAY.id)
    assert hass.states.get("button.gateway_restart").state == "unavailable"


async def test_site_device_is_kept(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """The site device stays even if the site has no devices left."""
    await _setup(hass, config_entry)

    mock_api["devices"].return_value = []
    await _refresh(config_entry, hass)

    assert _get_device(hass, config_entry, GATEWAY.id) is None
    assert _get_device(hass, config_entry, ACCESS_POINT.id) is None
    assert _get_device(hass, config_entry, SITE.id) is not None
    assert hass.states.get("sensor.default_connected_clients").state == "3"
    assert hass.states.get("sensor.default_adopted_devices").state == "0"


async def test_stale_device_removed_at_startup(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """A device removed while Home Assistant was not running is removed at setup.

    Devices without an identifier of the integration (clients created by device
    trackers via their MAC address) are kept.
    """
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    old = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, "dev-old")},
        name="Old switch",
    )
    old_entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "dev-old_state",
        config_entry=config_entry,
        device_id=old.id,
    )
    client = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, CLIENT_MAC)},
        name="Client",
    )

    await _setup(hass, config_entry)

    assert device_registry.async_get(old.id) is None
    assert entity_registry.async_get(old_entity.entity_id) is None
    assert device_registry.async_get(client.id) is not None
    assert _get_device(hass, config_entry, GATEWAY.id) is not None
    assert _get_device(hass, config_entry, ACCESS_POINT.id) is not None


async def test_device_returning_gets_new_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """A removed device that is adopted again gets its entities back."""
    await _setup(hass, config_entry)
    gateway_entities = _entity_ids(hass, GATEWAY.id)

    mock_api["devices"].return_value = [ACCESS_POINT]
    await _refresh(config_entry, hass)
    assert _entity_ids(hass, GATEWAY.id) == set()

    mock_api["devices"].return_value = [GATEWAY, ACCESS_POINT]
    await _refresh(config_entry, hass)
    # Ports and statistics come with the next update of the per-device data.
    await config_entry.runtime_data.details_coordinator.async_refresh()
    await config_entry.runtime_data.statistics_coordinator.async_refresh()
    await hass.async_block_till_done()

    assert _get_device(hass, config_entry, GATEWAY.id) is not None
    assert _entity_ids(hass, GATEWAY.id) == gateway_entities
    assert hass.states.get("button.gateway_restart").state != "unavailable"
    assert hass.states.get("sensor.gateway_cpu_utilization").state == "12.5"
    assert config_entry.state is ConfigEntryState.LOADED


async def test_returning_access_point_gets_radio_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Radio entities are recreated even without a details update in between."""
    online_ap = replace(ACCESS_POINT, state="ONLINE")
    mock_api["devices"].return_value = [GATEWAY, online_ap]
    await _setup(hass, config_entry)
    radio_entities = {
        entity_id
        for entity_id in _entity_ids(hass, ACCESS_POINT.id)
        if "ghz" in entity_id
    }
    assert radio_entities

    # Removed and adopted again between two updates of the device details.
    mock_api["devices"].return_value = [GATEWAY]
    await _refresh(config_entry, hass)
    mock_api["devices"].return_value = [GATEWAY, online_ap]
    await _refresh(config_entry, hass)
    await config_entry.runtime_data.details_coordinator.async_refresh()
    await config_entry.runtime_data.statistics_coordinator.async_refresh()
    await hass.async_block_till_done()

    assert radio_entities <= _entity_ids(hass, ACCESS_POINT.id)


async def test_remove_config_entry_device(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Only devices UniFi no longer reports can be deleted in the UI."""
    await _setup(hass, config_entry)
    assert config_entry.supports_remove_device
    device_registry = dr.async_get(hass)
    site = _get_device(hass, config_entry, SITE.id)
    gateway = _get_device(hass, config_entry, GATEWAY.id)
    access_point = _get_device(hass, config_entry, ACCESS_POINT.id)
    client = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, CLIENT_MAC)},
    )

    for device in (site, gateway, access_point, client):
        assert not await async_remove_config_entry_device(hass, config_entry, device)

    # The gateway is no longer reported; keep it in the registry to delete it by
    # hand (normally the next update removes it automatically).
    config_entry.runtime_data.site_coordinator.data.devices.pop(GATEWAY.id)
    assert await async_remove_config_entry_device(hass, config_entry, gateway)
    assert not await async_remove_config_entry_device(hass, config_entry, access_point)
    assert not await async_remove_config_entry_device(hass, config_entry, site)
