"""Device trackers for clients of UniFi Network Extended.

Only physical clients (wired/wireless) with a MAC address are tracked. The
API lists connected clients only, so a client missing from the list is
considered away.

As usual for router based trackers, Home Assistant creates trackers disabled
unless a device with the same MAC address is already known (e.g. from another
integration); they can be enabled individually.
"""

from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import UnifiNetworkExtendedConfigEntry
from .api import UnifiClient
from .const import CONF_TRACK_CLIENTS, DEFAULT_TRACK_CLIENTS
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

    if not entry.options.get(CONF_TRACK_CLIENTS, DEFAULT_TRACK_CLIENTS):
        # Tracking was switched off: remove the previously created trackers.
        for reg_entry in tracker_entries:
            registry.async_remove(reg_entry.entity_id)
        return

    coordinator = entry.runtime_data.site_coordinator
    site_id = coordinator.site.id
    known: set[str] = set()

    # Restore trackers of clients that are currently not connected.
    restored: list[UnifiClientTracker] = []
    for reg_entry in tracker_entries:
        mac = reg_entry.unique_id.removeprefix(f"{site_id}_")
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

    _async_add_new_clients()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_clients))


class UnifiClientTracker(CoordinatorEntity[UnifiSiteCoordinator], ScannerEntity):
    """Tracks whether a client is connected to the site."""

    def __init__(self, coordinator: UnifiSiteCoordinator, mac: str, name: str) -> None:
        """Initialize the tracker."""
        super().__init__(coordinator)
        self._mac = mac
        self._unique_id = f"{coordinator.site.id}_{mac}"
        self._attr_name = name

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
