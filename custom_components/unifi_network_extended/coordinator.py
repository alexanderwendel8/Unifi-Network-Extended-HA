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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    UnifiApiClient,
    UnifiApiError,
    UnifiClient,
    UnifiDevice,
    UnifiDeviceStatistics,
    UnifiInvalidAuth,
    UnifiPort,
    UnifiSite,
)
from .const import DOMAIN, STATISTICS_PARALLEL_REQUESTS

if TYPE_CHECKING:
    from . import UnifiNetworkExtendedConfigEntry

_LOGGER = logging.getLogger(__name__)


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
        try:
            devices, clients = await asyncio.gather(
                self.client.async_get_devices(self.site.id),
                self.client.async_get_clients(self.site.id),
            )
        except UnifiInvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except UnifiApiError as err:
            raise UpdateFailed(str(err)) from err
        return UnifiSiteData(
            devices={device.id: device for device in devices},
            clients={client.id: client for client in clients},
            clients_by_mac={
                client.mac_address.lower(): client
                for client in clients
                if client.mac_address
            },
        )


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


class UnifiPortsCoordinator(_UnifiPerDeviceCoordinator[dict[int, UnifiPort]]):
    """Polls the physical ports (link, speed, PoE) of every online device with ports."""

    _kind = "ports"

    def _include_device(self, device: UnifiDevice) -> bool:
        """Only devices that report physical ports."""
        return super()._include_device(device) and "ports" in device.interfaces

    async def _async_fetch(self, site_id: str, device_id: str) -> dict[int, UnifiPort]:
        """Fetch the ports of a device."""
        return await self.site_coordinator.client.async_get_device_ports(
            site_id, device_id
        )
