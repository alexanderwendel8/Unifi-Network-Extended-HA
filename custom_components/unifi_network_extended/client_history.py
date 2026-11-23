"""Remembers when tracked clients were last connected.

The official UniFi Network API only lists currently connected clients and has
no "last seen" time, so the integration keeps it itself (one store per config
entry). It is used to remove trackers of clients that have not been connected
for a long time.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

STORAGE_VERSION = 1
# A pending change is written after this delay (or when Home Assistant stops).
STORAGE_SAVE_DELAY = 300
# Clients are polled every few seconds; a day-based retention does not need
# that precision. Refreshing a time only once per hour keeps writes rare.
LAST_SEEN_RESOLUTION = timedelta(hours=1)


def _storage_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}.client_last_seen"


async def async_remove_client_history(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the stored data of a config entry."""
    await Store(hass, STORAGE_VERSION, _storage_key(entry_id)).async_remove()


class ClientHistory:
    """Last connection time per tracked client MAC address (lower case)."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the history."""
        self._store: Store[dict[str, dict[str, str]]] = Store(
            hass, STORAGE_VERSION, _storage_key(entry_id)
        )
        self._last_seen: dict[str, datetime] = {}
        self._dirty = False

    async def async_load(self) -> None:
        """Load the stored times."""
        data = await self._store.async_load() or {}
        for mac, value in data.get("last_seen", {}).items():
            if (last_seen := dt_util.parse_datetime(value)) is not None:
                self._last_seen[mac] = last_seen

    async def async_remove(self) -> None:
        """Forget all clients and delete the stored data."""
        self._last_seen.clear()
        self._dirty = False
        await self._store.async_remove()

    async def async_flush(self) -> None:
        """Write pending changes now (on unload)."""
        if self._dirty:
            await self._store.async_save(self._data())
            self._dirty = False

    def __contains__(self, mac: str) -> bool:
        """Return True if a time is known for the client."""
        return mac in self._last_seen

    @callback
    def async_mark_seen(self, macs: Iterable[str], now: datetime) -> None:
        """Set the last connection time of the given clients to now."""
        changed = False
        for mac in macs:
            last_seen = self._last_seen.get(mac)
            if last_seen is None or now - last_seen >= LAST_SEEN_RESOLUTION:
                self._last_seen[mac] = now
                changed = True
        if changed:
            self._async_schedule_save()

    @callback
    def async_add_missing(self, macs: Iterable[str], now: datetime) -> None:
        """Start the retention for clients without a known time.

        Trackers created before this history existed must not be removed
        immediately.
        """
        missing = [mac for mac in macs if mac not in self._last_seen]
        if missing:
            self.async_mark_seen(missing, now)

    @callback
    def async_stale(self, cutoff: datetime) -> list[str]:
        """Return the clients last connected at or before the cutoff."""
        return [mac for mac, seen in self._last_seen.items() if seen <= cutoff]

    @callback
    def async_forget(self, mac: str) -> None:
        """Remove a client from the history."""
        if self._last_seen.pop(mac, None) is not None:
            self._async_schedule_save()

    @callback
    def _async_schedule_save(self) -> None:
        self._dirty = True
        self._store.async_delay_save(self._data, STORAGE_SAVE_DELAY)

    @callback
    def _data(self) -> dict[str, dict[str, str]]:
        self._dirty = False
        return {
            "last_seen": {
                mac: last_seen.isoformat()
                for mac, last_seen in sorted(self._last_seen.items())
            }
        }
