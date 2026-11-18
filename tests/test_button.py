"""Tests for the restart buttons."""

from unittest.mock import AsyncMock

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_network_extended.api import (
    UnifiCannotConnect,
    UnifiInvalidAuth,
)
from custom_components.unifi_network_extended.const import DOMAIN

from .conftest import ACCESS_POINT, GATEWAY, SITE


def _entity_id(hass: HomeAssistant, device_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, f"{device_id}_restart"
    )
    assert entity_id
    return entity_id


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


async def test_restart_button(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Pressing the button restarts the device and refreshes the data."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    entity_id = _entity_id(hass, GATEWAY.id)
    assert entity_id == "button.gateway_restart"
    devices_calls = mock_api["devices"].await_count

    await _press(hass, entity_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    mock_api["restart"].assert_awaited_once_with(SITE.id, GATEWAY.id)
    assert mock_api["devices"].await_count > devices_calls


async def test_restart_button_unavailable_when_offline(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """Offline devices cannot be restarted."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)

    assert hass.states.get(_entity_id(hass, ACCESS_POINT.id)).state == (
        STATE_UNAVAILABLE
    )


async def test_restart_button_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """API errors are shown to the user."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    mock_api["restart"].side_effect = UnifiCannotConnect

    with pytest.raises(HomeAssistantError) as exc_info:
        await _press(hass, _entity_id(hass, GATEWAY.id))
    assert exc_info.value.translation_key == "restart_failed"
    assert exc_info.value.translation_placeholders["device"] == "Gateway"


async def test_restart_button_invalid_auth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_api: dict[str, AsyncMock]
) -> None:
    """An invalid API key starts the reauth flow."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    mock_api["restart"].side_effect = UnifiInvalidAuth

    with pytest.raises(HomeAssistantError) as exc_info:
        await _press(hass, _entity_id(hass, GATEWAY.id))
    assert exc_info.value.translation_key == "invalid_auth"

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
