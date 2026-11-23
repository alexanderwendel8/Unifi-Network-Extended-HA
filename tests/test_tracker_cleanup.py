"""Tests for removing trackers of clients that were not connected for long."""

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_HOME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.unifi_network_extended.const import (
    CLIENT_TRACKER_CLEANUP_INTERVAL,
    CLIENT_TRACKER_RETENTION,
    CONF_TRACK_CLIENTS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

from .conftest import NAS, PHONE, SITE

PHONE_MAC = PHONE.mac_address.lower()
NAS_MAC = NAS.mac_address.lower()
PHONE_UID = f"{SITE.id}_{PHONE_MAC}"
NAS_UID = f"{SITE.id}_{NAS_MAC}"
OLD_MAC = "de:ad:be:ef:00:01"
OLD_UID = f"{SITE.id}_{OLD_MAC}"


def _key(entry: MockConfigEntry) -> str:
    return f"{DOMAIN}.{entry.entry_id}.client_last_seen"


def _last_seen(hass_storage: dict[str, Any], entry: MockConfigEntry) -> dict:
    return hass_storage[_key(entry)]["data"]["last_seen"]


def _tracker_id(hass: HomeAssistant, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("device_tracker", DOMAIN, unique_id)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _disconnect_phone(
    hass: HomeAssistant,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_api["clients"].return_value = [NAS]
    await _tick(hass, freezer, timedelta(seconds=DEFAULT_SCAN_INTERVAL))


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize(("days", "removed"), [(180, True), (179, False)])
async def test_tracker_removed_after_retention_on_start(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    days: int,
    removed: bool,
) -> None:
    """At startup, trackers of clients gone for 180 days are removed."""
    await _setup(hass, config_entry)
    assert _tracker_id(hass, PHONE_UID)
    await _unload(hass, config_entry)
    assert PHONE_MAC in _last_seen(hass_storage, config_entry)

    mock_api["clients"].return_value = [NAS]
    freezer.tick(timedelta(days=days))
    await _setup(hass, config_entry)

    assert (_tracker_id(hass, PHONE_UID) is None) is removed
    # The connected client keeps its tracker.
    assert _tracker_id(hass, NAS_UID)
    # Pending changes are written on unload.
    await _unload(hass, config_entry)
    assert (PHONE_MAC not in _last_seen(hass_storage, config_entry)) is removed


async def test_tracker_removed_by_daily_cleanup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """While running, the daily cleanup removes stale trackers."""
    await _setup(hass, config_entry)
    await _disconnect_phone(hass, mock_api, freezer)

    await _tick(hass, freezer, CLIENT_TRACKER_RETENTION - timedelta(days=1))
    assert _tracker_id(hass, PHONE_UID)

    await _tick(hass, freezer, CLIENT_TRACKER_CLEANUP_INTERVAL)
    assert _tracker_id(hass, PHONE_UID) is None
    assert hass.states.get(f"device_tracker.{PHONE.name.lower()}") is None
    assert _tracker_id(hass, NAS_UID)

    # The change is written to the store (delayed).
    await _tick(hass, freezer, timedelta(minutes=10))
    assert list(_last_seen(hass_storage, config_entry)) == [NAS_MAC]


async def test_connected_client_never_removed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A connected client counts as seen, even with an old stored time."""
    long_ago = dt_util.utcnow() - timedelta(days=365)
    hass_storage[_key(config_entry)] = {
        "version": 1,
        "minor_version": 1,
        "key": _key(config_entry),
        "data": {"last_seen": {PHONE_MAC: long_ago.isoformat()}},
    }
    er.async_get(hass).async_get_or_create(
        "device_tracker", DOMAIN, PHONE_UID, config_entry=config_entry
    )

    await _setup(hass, config_entry)
    assert _tracker_id(hass, PHONE_UID)

    for _ in range(3):
        await _tick(hass, freezer, CLIENT_TRACKER_RETENTION)
        assert _tracker_id(hass, PHONE_UID)
    await _unload(hass, config_entry)
    last_seen = dt_util.parse_datetime(
        _last_seen(hass_storage, config_entry)[PHONE_MAC]
    )
    assert last_seen == dt_util.utcnow()


async def test_existing_trackers_kept_on_first_start(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Trackers from before the update start their retention at the first start."""
    er.async_get(hass).async_get_or_create(
        "device_tracker",
        DOMAIN,
        OLD_UID,
        config_entry=config_entry,
        original_name="Old phone",
    )
    assert _key(config_entry) not in hass_storage

    await _setup(hass, config_entry)
    assert _tracker_id(hass, OLD_UID)
    await _unload(hass, config_entry)
    assert OLD_MAC in _last_seen(hass_storage, config_entry)

    freezer.tick(CLIENT_TRACKER_RETENTION - timedelta(days=1))
    await _setup(hass, config_entry)
    assert _tracker_id(hass, OLD_UID)

    await _tick(hass, freezer, CLIENT_TRACKER_CLEANUP_INTERVAL)
    assert _tracker_id(hass, OLD_UID) is None


async def test_returning_client_gets_new_tracker(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A client showing up again after the removal is tracked again."""
    await _setup(hass, config_entry)
    await _disconnect_phone(hass, mock_api, freezer)
    await _tick(hass, freezer, CLIENT_TRACKER_RETENTION)
    assert _tracker_id(hass, PHONE_UID) is None

    mock_api["clients"].return_value = [PHONE, NAS]
    await _tick(hass, freezer, timedelta(seconds=DEFAULT_SCAN_INTERVAL))

    assert (entity_id := _tracker_id(hass, PHONE_UID))
    # Created disabled again, as before.
    entry = er.async_get(hass).async_get(entity_id)
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_enabled_tracker_and_own_device_removed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Enabled trackers are removed too, a device only they created goes away."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, PHONE_MAC)},
    )
    await _setup(hass, config_entry)
    entity_id = _tracker_id(hass, PHONE_UID)
    assert hass.states.get(entity_id).state == STATE_HOME
    assert er.async_get(hass).async_get(entity_id).device_id == device.id

    await _disconnect_phone(hass, mock_api, freezer)
    await _tick(hass, freezer, CLIENT_TRACKER_RETENTION)

    assert _tracker_id(hass, PHONE_UID) is None
    assert hass.states.get(entity_id) is None
    assert device_registry.async_get(device.id) is None


async def test_other_integration_device_kept(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Devices of other integrations (e.g. a companion app) are not deleted."""
    other_entry = MockConfigEntry(domain="mobile_app", title="Phone app")
    other_entry.add_to_hass(hass)
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=other_entry.entry_id,
        identifiers={("mobile_app", "phone")},
        connections={(dr.CONNECTION_NETWORK_MAC, PHONE_MAC)},
        name="Phone",
    )
    other_entity = er.async_get(hass).async_get_or_create(
        "sensor", "mobile_app", "battery", config_entry=other_entry, device_id=device.id
    )
    # Enabled tracker: Home Assistant links it to a device by its MAC address.
    er.async_get(hass).async_get_or_create(
        "device_tracker", DOMAIN, PHONE_UID, config_entry=config_entry
    )

    await _setup(hass, config_entry)
    tracker = er.async_get(hass).async_get(_tracker_id(hass, PHONE_UID))
    assert tracker.device_id is not None
    await _disconnect_phone(hass, mock_api, freezer)
    await _tick(hass, freezer, CLIENT_TRACKER_RETENTION)

    assert _tracker_id(hass, PHONE_UID) is None
    device = device_registry.async_get(device.id)
    assert device is not None
    assert device.identifiers == {("mobile_app", "phone")}
    # The device of the tracker (or its link to the app's device) is gone.
    assert not [
        own
        for own in dr.async_entries_for_config_entry(
            device_registry, config_entry.entry_id
        )
        if (dr.CONNECTION_NETWORK_MAC, PHONE_MAC) in own.connections
    ]
    assert er.async_get(hass).async_get(other_entity.entity_id).device_id == device.id


async def test_device_with_unifi_entities_kept(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A device still holding other entities of the entry is not released."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, PHONE_MAC)},
    )
    er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, "other", config_entry=config_entry, device_id=device.id
    )
    await _setup(hass, config_entry)
    await _disconnect_phone(hass, mock_api, freezer)
    await _tick(hass, freezer, CLIENT_TRACKER_RETENTION)

    assert _tracker_id(hass, PHONE_UID) is None
    assert device_registry.async_get(device.id) is not None


async def test_disable_tracking_clears_store(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    hass_storage: dict[str, Any],
) -> None:
    """Switching tracking off removes trackers and the stored times."""
    await _setup(hass, config_entry)
    await _unload(hass, config_entry)
    assert _key(config_entry) in hass_storage

    hass.config_entries.async_update_entry(
        config_entry, options={CONF_TRACK_CLIENTS: False}
    )
    await _setup(hass, config_entry)

    assert _tracker_id(hass, PHONE_UID) is None
    assert _tracker_id(hass, NAS_UID) is None
    assert _key(config_entry) not in hass_storage


async def test_store_removed_with_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api: dict[str, AsyncMock],
    hass_storage: dict[str, Any],
) -> None:
    """Removing the integration deletes its stored data."""
    await _setup(hass, config_entry)
    await _unload(hass, config_entry)
    assert _key(config_entry) in hass_storage

    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert _key(config_entry) not in hass_storage
