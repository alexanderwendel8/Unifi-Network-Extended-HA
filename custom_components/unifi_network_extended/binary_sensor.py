"""Binary sensors for UniFi Network Extended."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnifiNetworkExtendedConfigEntry
from .api import UnifiPort
from .entity import (
    UnifiDeviceEntity,
    UnifiPortEntity,
    UnifiPortEntityDescription,
    async_setup_port_entities,
)

PARALLEL_UPDATES = 0

FIRMWARE_UPDATE = BinarySensorEntityDescription(
    key="firmware_update",
    translation_key="firmware_update",
    device_class=BinarySensorDeviceClass.UPDATE,
    entity_category=EntityCategory.DIAGNOSTIC,
)


@dataclass(frozen=True, kw_only=True)
class UnifiPortBinarySensorDescription(
    UnifiPortEntityDescription, BinarySensorEntityDescription
):
    """Describes a binary sensor of a device port."""

    value_fn: Callable[[UnifiPort], bool | None]


PORT_BINARY_SENSORS: tuple[UnifiPortBinarySensorDescription, ...] = (
    UnifiPortBinarySensorDescription(
        key="link",
        translation_key="port_link",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda port: {"UP": True, "DOWN": False}.get(port.state),
    ),
    UnifiPortBinarySensorDescription(
        key="poe_enabled",
        translation_key="port_poe_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        exists_fn=lambda port: port.poe is not None,
        value_fn=lambda port: port.poe.enabled if port.poe else None,
    ),
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

    async_setup_port_entities(
        entry,
        entry.runtime_data.details_coordinator,
        PORT_BINARY_SENSORS,
        UnifiPortBinarySensor,
        async_add_entities,
    )


class UnifiFirmwareUpdateSensor(UnifiDeviceEntity, BinarySensorEntity):
    """Indicates that a firmware update is available (``firmwareUpdatable``)."""

    @property
    def is_on(self) -> bool | None:
        """Return True if a firmware update is available."""
        if (device := self.device) is None:
            return None
        return device.firmware_updatable


class UnifiPortBinarySensor(UnifiPortEntity, BinarySensorEntity):
    """Binary sensor of a device port."""

    entity_description: UnifiPortBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        if (port := self.port) is None:
            return None
        return self.entity_description.value_fn(port)
