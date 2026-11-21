"""Base entities for UniFi Network Extended."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import inspect

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceEntryType,
    DeviceInfo,
    DeviceRegistry,
)
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import (
    UnifiDevice,
    UnifiDeviceDetails,
    UnifiDeviceStatistics,
    UnifiPort,
    UnifiRadio,
    UnifiSite,
)
from .const import DOMAIN
from .coordinator import (
    UnifiDeviceDetailsCoordinator,
    UnifiSiteCoordinator,
    UnifiStatisticsCoordinator,
)

MANUFACTURER = "Ubiquiti"
SITE_MODEL = "UniFi Network site"

# Home Assistant 2026.8+ links child devices by the parent's registry ID
# (`via_device_id`); `via_device` (parent identifier) is deprecated there and
# removed in 2027.8. Older versions only know `via_device`.
SUPPORTS_VIA_DEVICE_ID = (
    "via_device_id" in inspect.signature(DeviceRegistry.async_get_or_create).parameters
)


def site_device_info(site: UnifiSite) -> DeviceInfo:
    """Return the device info of the site (service device)."""
    return DeviceInfo(
        identifiers={(DOMAIN, site.id)},
        name=site.name,
        manufacturer=MANUFACTURER,
        model=SITE_MODEL,
        entry_type=DeviceEntryType.SERVICE,
    )


def unifi_device_info(
    coordinator: UnifiSiteCoordinator, device: UnifiDevice
) -> DeviceInfo:
    """Return the device info of an adopted UniFi device, below the site device."""
    if SUPPORTS_VIA_DEVICE_ID:
        via: dict[str, str | tuple[str, str]] = {
            "via_device_id": coordinator.site_device_id
        }
    else:
        via = {"via_device": (DOMAIN, coordinator.site.id)}
    return DeviceInfo(
        identifiers={(DOMAIN, device.id)},
        connections={(CONNECTION_NETWORK_MAC, device.mac_address.lower())},
        name=device.name,
        manufacturer=MANUFACTURER,
        model=device.model,
        sw_version=device.firmware_version or None,
        **via,
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
            coordinator, coordinator.data.devices[device_id]
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
            site_coordinator, site_coordinator.data.devices[device_id]
        )

    @property
    def statistics(self) -> UnifiDeviceStatistics | None:
        """Return the latest statistics, None if the device is offline."""
        return self.coordinator.data.get(self.device_id)

    @property
    def available(self) -> bool:
        """Statistics are only available for online devices."""
        return super().available and self.statistics is not None


class UnifiDeviceDetailsEntity(CoordinatorEntity[UnifiDeviceDetailsCoordinator]):
    """Entity based on the details of an adopted UniFi device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UnifiDeviceDetailsCoordinator,
        description: EntityDescription,
        device_id: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_{description.key}"
        site_coordinator = coordinator.site_coordinator
        self._attr_device_info = unifi_device_info(
            site_coordinator, site_coordinator.data.devices[device_id]
        )

    @property
    def details(self) -> UnifiDeviceDetails | None:
        """Return the device details, None if the device is offline."""
        return self.coordinator.data.get(self.device_id)

    @property
    def available(self) -> bool:
        """Details are only available for online devices."""
        return super().available and self.details is not None


@dataclass(frozen=True, kw_only=True)
class UnifiPortEntityDescription(EntityDescription):
    """Describes an entity of a device port.

    ``exists_fn`` decides whether the port gets the entity at all (e.g. PoE
    entities only for PoE ports), ``enabled_fn`` whether it is enabled by default.
    """

    exists_fn: Callable[[UnifiPort], bool] = lambda port: True
    enabled_fn: Callable[[UnifiPort], bool] = lambda port: True


class UnifiPortEntity(CoordinatorEntity[UnifiDeviceDetailsCoordinator]):
    """Entity of a physical port, attached to the device the port belongs to."""

    _attr_has_entity_name = True
    entity_description: UnifiPortEntityDescription

    def __init__(
        self,
        coordinator: UnifiDeviceDetailsCoordinator,
        description: UnifiPortEntityDescription,
        device_id: str,
        port: UnifiPort,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.device_id = device_id
        self.port_idx = port.idx
        self._attr_unique_id = f"{device_id}_port{port.idx}_{description.key}"
        self._attr_translation_placeholders = {"port": str(port.idx)}
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default and description.enabled_fn(port)
        )
        site_coordinator = coordinator.site_coordinator
        self._attr_device_info = unifi_device_info(
            site_coordinator, site_coordinator.data.devices[device_id]
        )

    @property
    def port(self) -> UnifiPort | None:
        """Return the current port data, None if unknown (e.g. device offline)."""
        if (details := self.coordinator.data.get(self.device_id)) is None:
            return None
        return details.ports.get(self.port_idx)

    @property
    def available(self) -> bool:
        """Port data is only available while the device is online."""
        return super().available and self.port is not None


def async_setup_port_entities[EntityT: Entity](
    entry: ConfigEntry,
    coordinator: UnifiDeviceDetailsCoordinator,
    descriptions: Iterable[UnifiPortEntityDescription],
    entity_class: Callable[
        [UnifiDeviceDetailsCoordinator, UnifiPortEntityDescription, str, UnifiPort],
        EntityT,
    ],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add port entities now and for ports that appear later."""
    descriptions = tuple(descriptions)
    known: set[tuple[str, int]] = set()

    @callback
    def _async_add_new_ports() -> None:
        entities: list[EntityT] = []
        for device_id, details in coordinator.data.items():
            for port in details.ports.values():
                if (device_id, port.idx) in known:
                    continue
                known.add((device_id, port.idx))
                entities.extend(
                    entity_class(coordinator, description, device_id, port)
                    for description in descriptions
                    if description.exists_fn(port)
                )
        if entities:
            async_add_entities(entities)

    _async_add_new_ports()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_ports))


class _UnifiRadioEntity[
    CoordinatorT: (
        UnifiDeviceDetailsCoordinator,
        UnifiStatisticsCoordinator,
    )
](CoordinatorEntity[CoordinatorT]):
    """Entity of one radio band of an access point, e.g. "5 GHz channel"."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CoordinatorT,
        description: EntityDescription,
        device_id: str,
        band: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.device_id = device_id
        self.band = band
        band_key = band.replace(".", "_")
        self._attr_unique_id = f"{device_id}_radio_{band_key}_{description.key}"
        self._attr_translation_placeholders = {"band": band}
        site_coordinator = coordinator.site_coordinator
        self._attr_device_info = unifi_device_info(
            site_coordinator, site_coordinator.data.devices[device_id]
        )


class UnifiRadioEntity(_UnifiRadioEntity[UnifiDeviceDetailsCoordinator]):
    """Entity based on a radio of the device details (channel, width, standard)."""

    @property
    def radio(self) -> UnifiRadio | None:
        """Return the radio, None if unknown (e.g. access point offline)."""
        if (details := self.coordinator.data.get(self.device_id)) is None:
            return None
        return details.radios.get(self.band)

    @property
    def available(self) -> bool:
        """Radio data is only available while the access point is online."""
        return super().available and self.radio is not None


class UnifiRadioStatisticsEntity(_UnifiRadioEntity[UnifiStatisticsCoordinator]):
    """Entity based on the latest statistics of a radio (TX retries)."""

    @property
    def available(self) -> bool:
        """Statistics are only available while the access point is online."""
        statistics = self.coordinator.data.get(self.device_id)
        return (
            super().available
            and statistics is not None
            and self.band in statistics.radio_tx_retries_pct
        )


def async_setup_radio_entities[DataT](
    entry: ConfigEntry,
    coordinator: UnifiDeviceDetailsCoordinator | UnifiStatisticsCoordinator,
    bands_fn: Callable[[DataT], Iterable[str]],
    entity_factory: Callable[[str, str], Iterable[Entity]],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add radio entities now and for radios (or access points) that appear later."""
    known: set[tuple[str, str]] = set()

    @callback
    def _async_add_new_radios() -> None:
        entities: list[Entity] = []
        for device_id, data in coordinator.data.items():
            for band in bands_fn(data):
                if (device_id, band) in known:
                    continue
                known.add((device_id, band))
                entities.extend(entity_factory(device_id, band))
        if entities:
            async_add_entities(entities)

    _async_add_new_radios()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_radios))
