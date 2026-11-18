"""Config flow for the UniFi Network Extended integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import UnifiApiError, UnifiInvalidAuth, async_create_api_client
from .const import DEFAULT_PORT, DEFAULT_VERIFY_SSL, DOMAIN

_LOGGER = logging.getLogger(__name__)

PORT_SELECTOR = vol.All(
    NumberSelector(
        NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
    ),
    vol.Coerce(int),
)
API_KEY_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="off")
)


def _connection_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Return the schema for the connection settings (without API key default)."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)): str,
            vol.Required(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): PORT_SELECTOR,
            # The API key is never pre-filled in the UI.
            vol.Required(CONF_API_KEY): API_KEY_SELECTOR,
            vol.Required(
                CONF_VERIFY_SSL,
                default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            ): bool,
        }
    )


def _strip_input(user_input: dict[str, Any]) -> None:
    """Remove surrounding whitespace, e.g. from a pasted API key."""
    for key in (CONF_HOST, CONF_API_KEY):
        if key in user_input:
            user_input[key] = user_input[key].strip()


async def _async_validate_input(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> dict[str, str]:
    """Call GET /v1/info with the given data and return form errors (empty = ok)."""
    client = async_create_api_client(hass, data)
    try:
        await client.async_get_application_version()
    except UnifiInvalidAuth:
        return {"base": "invalid_auth"}
    except UnifiApiError as err:
        # Unreachable host, or no UniFi Network API at this address.
        _LOGGER.debug("Validation failed: %s", err)
        return {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unexpected exception while validating the API key")
        return {"base": "unknown"}
    return {}


class UnifiNetworkExtendedConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UniFi Network Extended."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step in the UI."""
        errors: dict[str, str] = {}

        if user_input is not None:
            _strip_input(user_input)
            self._async_abort_entries_match(
                {CONF_HOST: user_input[CONF_HOST], CONF_PORT: user_input[CONF_PORT]}
            )
            errors = await _async_validate_input(self.hass, user_input)
            if not errors:
                return self.async_create_entry(
                    title=f"UniFi Network ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _connection_schema({}), user_input
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow changing host, port, API key and SSL option via the UI."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            _strip_input(user_input)
            errors = await _async_validate_input(self.hass, user_input)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    title=f"UniFi Network ({user_input[CONF_HOST]})",
                    data_updates=user_input,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(entry.data),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication when the stored API key stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            _strip_input(user_input)
            errors = await _async_validate_input(
                self.hass, {**entry.data, **user_input}
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_API_KEY): API_KEY_SELECTOR}
            ),
            description_placeholders={CONF_HOST: entry.data[CONF_HOST]},
            errors=errors,
        )
