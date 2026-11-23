"""Device trackers for clients of UniFi Network Extended.

Only physical clients (wired/wireless) with a MAC address are tracked. The
API lists connected clients only, so a client missing from the list is
considered away.

As usual for router based trackers, Home Assistant creates trackers disabled
(up to 2026.x only when no device with the same MAC address is known yet);
they can be enabled individually.

Trackers of clients that have not been connected for CLIENT_TRACKER_RETENTION
are removed (see client_history.py).
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import UnifiNetworkExtendedConfigEntry
from .api import UnifiClient
from .client_history import ClientHistory
from .const import (
    CLIENT_TRACKER_CLEANUP_INTERVAL,
    CLIENT_TRACKER_RETENTION,
    CONF_TRACK_CLIENTS,
    DEFAULT_TRACK_CLIENTS,
    DOMAIN,
)
from .coordinator import UnifiSiteCoordinator

PARALLEL_UPDATES = 0

TRACKED_CLIENT_TYPES = ("WIRED", "WIRELESS")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiNetworkExtendedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up device trackers for clients."""
    registry = er.async_get(hass)
    tracker_entries = [
        reg_entry
        for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id)
        if reg_entry.domain == Platform.DEVICE_TRACKER
    ]
    history = ClientHistory(hass, entry.entry_id)

    if not entry.options.get(CONF_TRACK_CLIENTS, DEFAULT_TRACK_CLIENTS):
        # Tracking was switched off: remove the previously created trackers
        # and the remembered connection times.
        for reg_entry in tracker_entries:
            _async_remove_tracker(hass, entry, reg_entry.entity_id)
        await history.async_remove()
        return

    await history.async_load()
    entry.async_on_unload(history.async_flush)

    coordinator = entry.runtime_data.site_coordinator
    site_id = coordinator.site.id
    known: set[str] = set()

    @callback
    def _async_mark_connected_seen() -> None:
        history.async_mark_seen(
            (
                mac
                for mac, client in coordinator.data.clients_by_mac.items()
                if client.type in TRACKED_CLIENT_TYPES
            ),
            dt_util.utcnow(),
        )

    @callback
    def _async_remove_stale_trackers(_now: datetime | None = None) -> None:
        """Remove trackers of clients not connected within the retention."""
        connected = coordinator.data.clients_by_mac
        for mac in history.async_stale(dt_util.utcnow() - CLIENT_TRACKER_RETENTION):
            if mac in connected:
                continue
            if entity_id := registry.async_get_entity_id(
                Platform.DEVICE_TRACKER, DOMAIN, f"{site_id}_{mac}"
            ):
                _async_remove_tracker(hass, entry, entity_id)
            history.async_forget(mac)
            # A client showing up again gets a new tracker.
            known.discard(mac)

    # Trackers created before the history existed start their retention now.
    macs = {
        reg_entry.unique_id.removeprefix(f"{site_id}_") for reg_entry in tracker_entries
    }
    history.async_add_missing(macs, dt_util.utcnow())
    _async_mark_connected_seen()
    _async_remove_stale_trackers()

    # Restore trackers of clients that are currently not connected.
    restored: list[UnifiClientTracker] = []
    for reg_entry in tracker_entries:
        mac = reg_entry.unique_id.removeprefix(f"{site_id}_")
        if registry.async_get(reg_entry.entity_id) is None:
            continue  # removed as stale
        known.add(mac)
        restored.append(
            UnifiClientTracker(coordinator, mac, reg_entry.original_name or mac.upper())
        )
    async_add_entities(restored)

    @callback
    def _async_add_new_clients() -> None:
        new_clients: dict[str, UnifiClient] = {
            mac: client
            for mac, client in coordinator.data.clients_by_mac.items()
            if mac not in known and client.type in TRACKED_CLIENT_TYPES
        }
        if not new_clients:
            return
        known.update(new_clients)
        async_add_entities(
            UnifiClientTracker(coordinator, mac, client.name)
            for mac, client in new_clients.items()
        )

    @callback
    def _async_coordinator_updated() -> None:
        if coordinator.last_update_success:
            _async_mark_connected_seen()
        _async_add_new_clients()

    _async_add_new_clients()
    entry.async_on_unload(coordinator.async_add_listener(_async_coordinator_updated))
    entry.async_on_unload(
        async_track_time_interval(
            hass, _async_remove_stale_trackers, CLIENT_TRACKER_CLEANUP_INTERVAL
        )
    )


@callback
def _async_remove_tracker(
    hass: HomeAssistant, entry: UnifiNetworkExtendedConfigEntry, entity_id: str
) -> None:
    """Remove a tracker and the device only it created."""
    entity_registry = er.async_get(hass)
    if (reg_entry := entity_registry.async_get(entity_id)) is None:
        return
    device_id = reg_entry.device_id
    entity_registry.async_remove(entity_id)
    if device_id is not None:
        _async_release_device(hass, entry, device_id)


@callback
def _async_release_device(
    hass: HomeAssistant, entry: UnifiNetworkExtendedConfigEntry, device_id: str
) -> None:
    """Release the device of a removed tracker from this config entry.

    Trackers describe their client by MAC address only. Home Assistant creates a
    device for them, or (before 2026.10) adds this config entry to the device of
    another integration with the same MAC address, e.g. the phone from the
    companion app. Such devices are kept, only this config entry is removed.
    """
    device_registry = dr.async_get(hass)
    if (device := device_registry.async_get(device_id)) is None:
        return
    # Since Home Assistant 2026.10 a device belongs to a single config entry.
    if (owner := getattr(device, "config_entry_id", None)) is not None:
        owners = {owner}
    else:
        owners = set(device.config_entries)
    if (
        entry.entry_id not in owners
        # UniFi devices and the site are described by identifiers.
        or any(domain == DOMAIN for domain, _ in device.identifiers)
        or any(
            conn_type != CONNECTION_NETWORK_MAC for conn_type, _ in device.connections
        )
        or any(
            other.config_entry_id == entry.entry_id
            for other in er.async_entries_for_device(
                er.async_get(hass), device_id, include_disabled_entities=True
            )
        )
    ):
        return
    if owners == {entry.entry_id}:
        device_registry.async_remove_device(device_id)
    else:
        device_registry.async_update_device(
            device_id, remove_config_entry_id=entry.entry_id
        )


class UnifiClientTracker(CoordinatorEntity[UnifiSiteCoordinator], ScannerEntity):
    """Tracks whether a client is connected to the site."""

    def __init__(self, coordinator: UnifiSiteCoordinator, mac: str, name: str) -> None:
        """Initialize the tracker."""
        super().__init__(coordinator)
        self._mac = mac
        self._unique_id = f"{coordinator.site.id}_{mac}"
        self._attr_name = name
        # Home Assistant 2026.11+ expects the tracked device described by its MAC
        # address (linking it to a device another integration already knows).
        # Older versions ignore this, ScannerEntity.device_info is final there.
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, mac)}, name=name
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID per site (ScannerEntity defaults to the MAC).

        A client can be connected to several sites.
        """
        return self._unique_id

    @property
    def _client(self) -> UnifiClient | None:
        return self.coordinator.data.clients_by_mac.get(self._mac)

    @property
    def is_connected(self) -> bool:
        """Return True if the client is currently connected."""
        return self._client is not None

    @property
    def source_type(self) -> SourceType:
        """Return the source type."""
        return SourceType.ROUTER

    @property
    def mac_address(self) -> str:
        """Return the MAC address (links the tracker to matching devices)."""
        return self._mac

    @property
    def ip_address(self) -> str | None:
        """Return the current IP address."""
        return client.ip_address if (client := self._client) else None

    @property
    def hostname(self) -> str | None:
        """Return the client name as known by UniFi."""
        return client.name if (client := self._client) else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return connection details while connected."""
        if (client := self._client) is None:
            return {}
        return {
            "connection_type": client.type.lower(),
            "connected_at": (
                client.connected_at.isoformat() if client.connected_at else None
            ),
        }
