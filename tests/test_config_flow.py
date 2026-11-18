"""Tests for the UniFi Network Extended config flow."""

from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_network_extended.api import (
    UnifiApiError,
    UnifiCannotConnect,
    UnifiInvalidAuth,
)
from custom_components.unifi_network_extended.const import DOMAIN

USER_INPUT = {
    CONF_HOST: "192.168.1.1",
    CONF_PORT: 443,
    CONF_API_KEY: "secret-key",
    CONF_VERIFY_SSL: False,
}

VALIDATE = (
    "custom_components.unifi_network_extended.api.UnifiApiClient"
    ".async_get_application_version"
)


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Avoid setting up the entry during flow tests."""
    with patch(
        "custom_components.unifi_network_extended.async_setup_entry",
        return_value=True,
    ):
        yield


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test a successful setup through the UI."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    with patch(VALIDATE, return_value="9.1.0"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT


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
    with patch(VALIDATE, side_effect=side_effect):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    with patch(VALIDATE, return_value="9.1.0"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(hass: HomeAssistant) -> None:
    """Test that the same host/port cannot be added twice."""
    MockConfigEntry(domain=DOMAIN, data=USER_INPUT).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(hass: HomeAssistant) -> None:
    """Test re-authentication updates the stored API key."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT)
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    with patch(VALIDATE, return_value="9.1.0"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: " new-key "}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new-key"


async def test_reconfigure_flow(hass: HomeAssistant) -> None:
    """Test reconfiguring the connection settings."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT)
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    with patch(VALIDATE, return_value="9.1.0"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**USER_INPUT, CONF_PORT: 8443, CONF_VERIFY_SSL: True},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PORT] == 8443
    assert entry.data[CONF_VERIFY_SSL] is True
