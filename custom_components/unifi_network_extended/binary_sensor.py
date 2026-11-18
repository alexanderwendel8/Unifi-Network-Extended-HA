"""Binary sensors for UniFi Network Extended."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnifiNetworkExtendedConfigEntry
from .entity import UnifiDeviceEntity

PARALLEL_UPDATES = 0

FIRMWARE_UPDATE = BinarySensorEntityDescription(
    key="firmware_update",
    translation_key="firmware_update",
    device_class=BinarySensorDeviceClass.UPDATE,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiNetworkExtendedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data.site_coordinator
    known: set[str] = set()

    @callback
    def _async_add_new_devices() -> None:
        new_ids = set(coordinator.data.devices) - known
        if not new_ids:
            return
        known.update(new_ids)
        async_add_entities(
            UnifiFirmwareUpdateSensor(coordinator, FIRMWARE_UPDATE, device_id)
            for device_id in new_ids
        )

    _async_add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_devices))


class UnifiFirmwareUpdateSensor(UnifiDeviceEntity, BinarySensorEntity):
    """Indicates that a firmware update is available (``firmwareUpdatable``)."""

    @property
    def is_on(self) -> bool | None:
        """Return True if a firmware update is available."""
        if (device := self.device) is None:
            return None
        return device.firmware_updatable
