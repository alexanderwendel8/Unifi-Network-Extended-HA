"""Tests for the UniFi Network Extended config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_network_extended.api import (
    UnifiApiError,
    UnifiCannotConnect,
    UnifiInvalidAuth,
    UnifiSite,
)
from custom_components.unifi_network_extended.const import CONF_SITE_ID, DOMAIN

USER_INPUT = {
    CONF_HOST: "192.168.1.1",
    CONF_PORT: 443,
    CONF_API_KEY: "secret-key",
    CONF_VERIFY_SSL: False,
}
DEFAULT_SITE = UnifiSite("site-default", "Default", "default")
OFFICE_SITE = UnifiSite("site-office", "Office", "office")
ENTRY_DATA = {**USER_INPUT, CONF_SITE_ID: DEFAULT_SITE.id}

GET_SITES = (
    "custom_components.unifi_network_extended.api.UnifiApiClient.async_get_sites"
)


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Avoid setting up the entry during flow tests."""
    with patch(
        "custom_components.unifi_network_extended.async_setup_entry",
        return_value=True,
    ):
        yield


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Default", unique_id=DEFAULT_SITE.id, data=ENTRY_DATA
    )
    entry.add_to_hass(hass)
    return entry


async def _start_user_flow(hass: HomeAssistant, sites: list[UnifiSite]) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch(GET_SITES, return_value=sites):
        return await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )


async def test_single_site_is_selected_automatically(hass: HomeAssistant) -> None:
    """With one site the entry is created without asking."""
    result = await _start_user_flow(hass, [DEFAULT_SITE])

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Default"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == DEFAULT_SITE.id


async def test_multiple_sites_ask_for_selection(hass: HomeAssistant) -> None:
    """With several sites the user picks one."""
    result = await _start_user_flow(hass, [OFFICE_SITE, DEFAULT_SITE])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "site"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SITE_ID: OFFICE_SITE.id}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Office"
    assert result["data"] == {**USER_INPUT, CONF_SITE_ID: OFFICE_SITE.id}


async def test_configured_sites_are_not_offered(hass: HomeAssistant) -> None:
    """Already configured sites are hidden from the selection."""
    _entry(hass)
    result = await _start_user_flow(hass, [DEFAULT_SITE, OFFICE_SITE])

    options = result["data_schema"].schema[CONF_SITE_ID].config["options"]
    assert [option["value"] for option in options] == [OFFICE_SITE.id]


async def test_all_sites_configured_aborts(hass: HomeAssistant) -> None:
    """Abort when every site of the controller is already configured."""
    _entry(hass)
    result = await _start_user_flow(hass, [DEFAULT_SITE])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_no_sites_aborts(hass: HomeAssistant) -> None:
    """Abort when the API key sees no sites."""
    result = await _start_user_flow(hass, [])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_sites"


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (UnifiInvalidAuth, "invalid_auth"),
        (UnifiCannotConnect, "cannot_connect"),
        (UnifiApiError, "cannot_connect"),
        (RuntimeError, "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, side_effect: type[Exception], error: str
) -> None:
    """Test errors are shown and the flow can recover."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(GET_SITES, side_effect=side_effect):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    with patch(GET_SITES, return_value=[DEFAULT_SITE]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_reauth_flow(hass: HomeAssistant) -> None:
    """Test re-authentication updates the stored API key."""
    entry = _entry(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    with patch(GET_SITES, return_value=[DEFAULT_SITE]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: " new-key "}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new-key"


async def test_reauth_site_missing(hass: HomeAssistant) -> None:
    """A key without access to the configured site is rejected."""
    entry = _entry(hass)

    result = await entry.start_reauth_flow(hass)
    with patch(GET_SITES, return_value=[OFFICE_SITE]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "other-key"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "site_not_found"}
    assert entry.data[CONF_API_KEY] == "secret-key"


async def test_reconfigure_flow(hass: HomeAssistant) -> None:
    """Test reconfiguring the connection settings keeps the site."""
    entry = _entry(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    with patch(GET_SITES, return_value=[DEFAULT_SITE]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**USER_INPUT, CONF_PORT: 8443, CONF_VERIFY_SSL: True},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PORT] == 8443
    assert entry.data[CONF_VERIFY_SSL] is True
    assert entry.data[CONF_SITE_ID] == DEFAULT_SITE.id


async def test_reconfigure_site_missing(hass: HomeAssistant) -> None:
    """Reconfiguring to a controller without the site is rejected."""
    entry = _entry(hass)

    result = await entry.start_reconfigure_flow(hass)
    with patch(GET_SITES, return_value=[OFFICE_SITE]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_HOST: "10.0.0.1"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "site_not_found"}


async def test_options_flow(hass: HomeAssistant) -> None:
    """Polling intervals and client tracking can be changed."""
    entry = _entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"scan_interval": 15, "statistics_interval": 120, "track_clients": False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "scan_interval": 15,
        "statistics_interval": 120,
        "track_clients": False,
    }
