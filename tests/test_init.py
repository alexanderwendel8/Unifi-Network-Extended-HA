"""Tests for setting up and unloading a config entry."""

from unittest.mock import patch

import pytest

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_network_extended.api import (
    UnifiCannotConnect,
    UnifiInvalidAuth,
    UnifiSite,
)
from custom_components.unifi_network_extended.const import CONF_SITE_ID, DOMAIN

SITE = UnifiSite("site-default", "Default", "default")
GET_SITES = (
    "custom_components.unifi_network_extended.api.UnifiApiClient.async_get_sites"
)


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a config entry added to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Default",
        unique_id=SITE.id,
        data={
            CONF_HOST: "192.168.1.1",
            CONF_PORT: 443,
            CONF_API_KEY: "secret-key",
            CONF_VERIFY_SSL: True,
            CONF_SITE_ID: SITE.id,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_and_unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The entry loads with the configured site and unloads again."""
    with patch(GET_SITES, return_value=[SITE]):
        assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.site == SITE

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    ("kwargs", "state"),
    [
        ({"side_effect": UnifiCannotConnect}, ConfigEntryState.SETUP_RETRY),
        ({"side_effect": UnifiInvalidAuth}, ConfigEntryState.SETUP_ERROR),
        ({"return_value": []}, ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_setup_failures(
    hass: HomeAssistant, entry: MockConfigEntry, kwargs: dict, state: ConfigEntryState
) -> None:
    """Connection errors retry; invalid keys and missing sites do not."""
    with patch(GET_SITES, **kwargs):
        await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is state


async def test_invalid_key_starts_reauth(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """An invalid API key starts the reauth flow."""
    with patch(GET_SITES, side_effect=UnifiInvalidAuth):
        await hass.config_entries.async_setup(entry.entry_id)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
