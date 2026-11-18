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


class UnifiStatisticsCoordinator(
    DataUpdateCoordinator[dict[str, UnifiDeviceStatistics]]
):
    """Polls the latest statistics of every online device.

    The API needs one request per device, so this runs less often than the
    site coordinator and limits the number of parallel requests.
    """

    config_entry: UnifiNetworkExtendedConfigEntry

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
            name=f"{DOMAIN} {site_coordinator.site.name} statistics",
            update_interval=timedelta(seconds=interval),
        )
        self._site_coordinator = site_coordinator
        self._semaphore = asyncio.Semaphore(STATISTICS_PARALLEL_REQUESTS)

    async def _async_update_data(self) -> dict[str, UnifiDeviceStatistics]:
        """Fetch statistics for all online devices.

        A failing device is skipped; only a total failure marks the update failed.
        """
        client = self._site_coordinator.client
        site_id = self._site_coordinator.site.id
        device_ids = [
            device.id
            for device in self._site_coordinator.data.devices.values()
            if device.state == "ONLINE"
        ]

        async def fetch(device_id: str) -> UnifiDeviceStatistics:
            async with self._semaphore:
                return await client.async_get_device_statistics(site_id, device_id)

        results = await asyncio.gather(
            *(fetch(device_id) for device_id in device_ids), return_exceptions=True
        )

        statistics: dict[str, UnifiDeviceStatistics] = {}
        errors: list[BaseException] = []
        for device_id, result in zip(device_ids, results, strict=True):
            if isinstance(result, UnifiDeviceStatistics):
                statistics[device_id] = result
            elif isinstance(result, UnifiInvalidAuth):
                raise ConfigEntryAuthFailed(str(result)) from result
            elif isinstance(result, UnifiApiError):
                _LOGGER.debug("Statistics for device %s failed: %s", device_id, result)
                errors.append(result)
            else:
                raise result

        if device_ids and not statistics:
            raise UpdateFailed(f"Fetching device statistics failed: {errors[0]}")
        return statistics
