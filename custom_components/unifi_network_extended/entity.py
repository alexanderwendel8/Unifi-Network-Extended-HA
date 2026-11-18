"""Base entities for UniFi Network Extended."""

from __future__ import annotations

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceEntryType,
    DeviceInfo,
)
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import UnifiDevice, UnifiDeviceStatistics, UnifiSite
from .const import DOMAIN
from .coordinator import UnifiSiteCoordinator, UnifiStatisticsCoordinator

MANUFACTURER = "Ubiquiti"


def site_device_info(site: UnifiSite) -> DeviceInfo:
    """Return the device info of the site (service device)."""
    return DeviceInfo(
        identifiers={(DOMAIN, site.id)},
        name=site.name,
        manufacturer=MANUFACTURER,
        model="UniFi Network site",
        entry_type=DeviceEntryType.SERVICE,
    )


def unifi_device_info(site: UnifiSite, device: UnifiDevice) -> DeviceInfo:
    """Return the device info of an adopted UniFi device."""
    return DeviceInfo(
        identifiers={(DOMAIN, device.id)},
        connections={(CONNECTION_NETWORK_MAC, device.mac_address.lower())},
        name=device.name,
        manufacturer=MANUFACTURER,
        model=device.model,
        sw_version=device.firmware_version or None,
        via_device=(DOMAIN, site.id),
    )


class UnifiSiteEntity(CoordinatorEntity[UnifiSiteCoordinator]):
    """Entity belonging to the site device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: UnifiSiteCoordinator, description: EntityDescription
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.site.id}_{description.key}"
        self._attr_device_info = site_device_info(coordinator.site)


class UnifiDeviceEntity(CoordinatorEntity[UnifiSiteCoordinator]):
    """Entity belonging to an adopted UniFi device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UnifiSiteCoordinator,
        description: EntityDescription,
        device_id: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_device_info = unifi_device_info(
            coordinator.site, coordinator.data.devices[device_id]
        )

    @property
    def device(self) -> UnifiDevice | None:
        """Return the current device data, None if it was removed."""
        return self.coordinator.data.devices.get(self.device_id)

    @property
    def available(self) -> bool:
        """Return if the device still exists."""
        return super().available and self.device is not None


class UnifiDeviceStatisticsEntity(CoordinatorEntity[UnifiStatisticsCoordinator]):
    """Entity based on the latest statistics of an adopted UniFi device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UnifiStatisticsCoordinator,
        site_coordinator: UnifiSiteCoordinator,
        description: EntityDescription,
        device_id: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_device_info = unifi_device_info(
            site_coordinator.site, site_coordinator.data.devices[device_id]
        )

    @property
    def statistics(self) -> UnifiDeviceStatistics | None:
        """Return the latest statistics, None if the device is offline."""
        return self.coordinator.data.get(self.device_id)

    @property
    def available(self) -> bool:
        """Statistics are only available for online devices."""
        return super().available and self.statistics is not None
