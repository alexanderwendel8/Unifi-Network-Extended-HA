"""Data update coordinators for UniFi Network Extended.

The official UniFi Network API has no push mechanism, so data is polled.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    UnifiApiClient,
    UnifiApiError,
    UnifiClient,
    UnifiDevice,
    UnifiDeviceDetails,
    UnifiDeviceStatistics,
    UnifiInvalidAuth,
    UnifiSite,
)
from .const import APPLICATION_INFO_INTERVAL, DOMAIN, STATISTICS_PARALLEL_REQUESTS

if TYPE_CHECKING:
    from . import UnifiNetworkExtendedConfigEntry

_LOGGER = logging.getLogger(__name__)

# Home Assistant 2026.9+ ties a device to a single config entry
# (`DeviceEntry.config_entry_id`) and deprecates `remove_config_entry_id`; a stale
# device is deleted with `async_remove_device` there. Older versions share devices
# between config entries, so only this entry is detached from the device.
SINGLE_CONFIG_ENTRY_DEVICES = hasattr(dr.DeviceEntry, "config_entry_id")


@dataclass(frozen=True, slots=True)
class UnifiSiteData:
    """Devices and clients of a site, keyed by their ID."""

    devices: dict[str, UnifiDevice]
    clients: dict[str, UnifiClient]
    clients_by_mac: dict[str, UnifiClient]


class UnifiSiteCoordinator(DataUpdateCoordinator[UnifiSiteData]):
    """Polls adopted devices and connected clients of a site."""

    config_entry: UnifiNetworkExtendedConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: UnifiNetworkExtendedConfigEntry,
        client: UnifiApiClient,
        site: UnifiSite,
        site_device_id: str,
        interval: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {site.name}",
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self.site = site
        # Registry ID of the site device, parent of all UniFi devices.
        self.site_device_id = site_device_id

    async def _async_update_data(self) -> UnifiSiteData:
        """Fetch devices and clients in parallel."""
        # Devices UniFi still reports, but with invalid data (skipped).
        skipped_ids: set[str] = set()
        try:
            devices, clients = await asyncio.gather(
                self.client.async_get_devices(self.site.id, skipped_ids=skipped_ids),
                self.client.async_get_clients(self.site.id),
            )
        except UnifiInvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except UnifiApiError as err:
            raise UpdateFailed(str(err)) from err
        # Only reached after a complete, successful fetch: every adopted device
        # (including offline ones) is in the response, so a missing one is gone.
        # Devices skipped for invalid data still exist and are kept.
        self._async_remove_stale_devices(
            {device.id for device in devices} | skipped_ids
        )
        return UnifiSiteData(
            devices={device.id: device for device in devices},
            clients={client.id: client for client in clients},
            clients_by_mac={
                client.mac_address.lower(): client
                for client in clients
                if client.mac_address
            },
        )

    def _async_remove_stale_devices(self, current_ids: set[str]) -> None:
        """Remove UniFi devices from the registry that UniFi no longer reports.

        Compares against the device registry instead of the previous update, so
        devices removed while Home Assistant was not running are found as well. The
        site device and devices without an identifier of this integration (e.g.
        clients created by device trackers) are kept. Removing a device also removes
        its entities.
        """
        registry = dr.async_get(self.hass)
        entry_id = self.config_entry.entry_id
        for device in dr.async_entries_for_config_entry(registry, entry_id):
            unifi_ids = {
                identifier[1]
                for identifier in device.identifiers
                if identifier[0] == DOMAIN
            }
            if (
                not unifi_ids
                or device.id == self.site_device_id
                or self.site.id in unifi_ids
                or unifi_ids & current_ids
            ):
                continue
            _LOGGER.debug(
                "Removing device %s, no longer reported by UniFi", device.name
            )
            if SINGLE_CONFIG_ENTRY_DEVICES:
                registry.async_remove_device(device.id)
            else:
                # Deletes the device unless another config entry still uses it.
                registry.async_update_device(device.id, remove_config_entry_id=entry_id)


class UnifiApplicationInfoCoordinator(DataUpdateCoordinator[str]):
    """Polls the version of the UniFi Network application (``GET /v1/info``).

    Runs on its own, hourly schedule: the version only changes with an update of
    the Network application, so it is not worth a request on every site poll.
    Listeners are only notified when the version (or availability) changes.
    """

    config_entry: UnifiNetworkExtendedConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: UnifiNetworkExtendedConfigEntry,
        client: UnifiApiClient,
        site: UnifiSite,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {site.name} application info",
            update_interval=timedelta(seconds=APPLICATION_INFO_INTERVAL),
            always_update=False,
        )
        self.client = client

    async def _async_update_data(self) -> str:
        """Fetch the application version."""
        try:
            return await self.client.async_get_application_version()
        except UnifiInvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except UnifiApiError as err:
            raise UpdateFailed(str(err)) from err


class _UnifiPerDeviceCoordinator[DataT](DataUpdateCoordinator[dict[str, DataT]]):
    """Polls data that needs one request per device.

    Runs less often than the site coordinator and limits the number of parallel
    requests. A failing device is skipped; only a total failure marks the update
    as failed.
    """

    config_entry: UnifiNetworkExtendedConfigEntry
    _kind: str

    def __init__(
        self,
        hass: HomeAssistant,
        entry: UnifiNetworkExtendedConfigEntry,
        site_coordinator: UnifiSiteCoordinator,
        interval: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {site_coordinator.site.name} {self._kind}",
            update_interval=timedelta(seconds=interval),
        )
        self.site_coordinator = site_coordinator
        self._semaphore = asyncio.Semaphore(STATISTICS_PARALLEL_REQUESTS)
        # Empty until the first refresh, which runs in the background after setup.
        self.data = {}

    def _include_device(self, device: UnifiDevice) -> bool:
        """Return True if data should be fetched for this device."""
        return device.state == "ONLINE"

    async def _async_fetch(self, site_id: str, device_id: str) -> DataT:
        """Fetch the data of one device."""
        raise NotImplementedError

    async def _async_update_data(self) -> dict[str, DataT]:
        """Fetch the data of all included devices."""
        site_id = self.site_coordinator.site.id
        device_ids = [
            device.id
            for device in self.site_coordinator.data.devices.values()
            if self._include_device(device)
        ]

        async def fetch(device_id: str) -> DataT:
            async with self._semaphore:
                return await self._async_fetch(site_id, device_id)

        results = await asyncio.gather(
            *(fetch(device_id) for device_id in device_ids), return_exceptions=True
        )

        data: dict[str, DataT] = {}
        errors: list[BaseException] = []
        for device_id, result in zip(device_ids, results, strict=True):
            if isinstance(result, UnifiInvalidAuth):
                raise ConfigEntryAuthFailed(str(result)) from result
            if isinstance(result, UnifiApiError):
                _LOGGER.debug(
                    "Fetching %s of device %s failed: %s", self._kind, device_id, result
                )
                errors.append(result)
            elif isinstance(result, BaseException):
                # Unreadable responses arrive as UnifiResponseError (handled
                # above); anything else is a bug or a cancellation and is passed on.
                raise result
            else:
                data[device_id] = result

        if device_ids and not data:
            raise UpdateFailed(f"Fetching device {self._kind} failed: {errors[0]}")
        return data


class UnifiStatisticsCoordinator(_UnifiPerDeviceCoordinator[UnifiDeviceStatistics]):
    """Polls the latest statistics of every online device."""

    _kind = "statistics"

    async def _async_fetch(self, site_id: str, device_id: str) -> UnifiDeviceStatistics:
        """Fetch the latest statistics of a device."""
        return await self.site_coordinator.client.async_get_device_statistics(
            site_id, device_id
        )


class UnifiDeviceDetailsCoordinator(_UnifiPerDeviceCoordinator[UnifiDeviceDetails]):
    """Polls the details (ports, uplink, provisioning) of every online device."""

    _kind = "details"

    async def _async_fetch(self, site_id: str, device_id: str) -> UnifiDeviceDetails:
        """Fetch the details of a device."""
        return await self.site_coordinator.client.async_get_device_details(
            site_id, device_id
        )
