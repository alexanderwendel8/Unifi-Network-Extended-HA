"""Buttons for UniFi Network Extended."""

from __future__ import annotations

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnifiNetworkExtendedConfigEntry
from .api import UnifiApiError, UnifiInvalidAuth
from .const import DOMAIN
from .entity import UnifiDeviceEntity

# Send one action at a time to the controller.
PARALLEL_UPDATES = 1

RESTART = ButtonEntityDescription(
    key="restart",
    device_class=ButtonDeviceClass.RESTART,
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiNetworkExtendedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""
    coordinator = entry.runtime_data.site_coordinator
    known: set[str] = set()

    @callback
    def _async_add_new_devices() -> None:
        new_ids = set(coordinator.data.devices) - known
        if not new_ids:
            return
        known.update(new_ids)
        async_add_entities(
            UnifiRestartButton(coordinator, RESTART, device_id) for device_id in new_ids
        )

    _async_add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_devices))


class UnifiRestartButton(UnifiDeviceEntity, ButtonEntity):
    """Restarts an adopted UniFi device."""

    @property
    def available(self) -> bool:
        """A restart can only be sent to an online device."""
        return (
            super().available
            and self.device is not None
            and self.device.state == "ONLINE"
        )

    async def async_press(self) -> None:
        """Send the restart action."""
        coordinator = self.coordinator
        try:
            await coordinator.client.async_restart_device(
                coordinator.site.id, self.device_id
            )
        except UnifiInvalidAuth as err:
            coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except UnifiApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="restart_failed",
                translation_placeholders={
                    "device": self.device.name if self.device else self.device_id,
                    "error": str(err),
                },
            ) from err

        # Show the new device state (e.g. offline while rebooting) right away.
        await coordinator.async_request_refresh()
