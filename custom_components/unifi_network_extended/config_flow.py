"""Config flow for the UniFi Network Extended integration."""

from __future__ import annotations

from collections.abc import Mapping
from ipaddress import ip_address
import logging
import re
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util.network import is_host_valid, is_ipv6_address
import voluptuous as vol

from .api import UnifiApiError, UnifiInvalidAuth, UnifiSite, async_create_api_client
from .const import (
    CONF_SITE_ID,
    CONF_STATISTICS_INTERVAL,
    CONF_TRACK_CLIENTS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STATISTICS_INTERVAL,
    DEFAULT_TRACK_CLIENTS,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

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
            vol.Required(
                CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)
            ): str,
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


_SCHEME = re.compile(r"^https?://", re.IGNORECASE)
_PORT = re.compile(r"^[0-9]{1,5}$")


def _parse_host(value: str) -> tuple[str, int | None] | None:
    """Split a host input into (host, port), or None if it is invalid.

    Accepts a hostname, an IPv4 or an IPv6 address. Tolerates what users often
    paste instead: an ``http(s)://`` scheme, a trailing slash or path, brackets
    around an IPv6 address and a port (``host:8443``, ``[fd00::1]:8443``).
    The returned host has no brackets; the API client adds them for the URL.
    """
    host = _SCHEME.sub("", value.strip())
    # Drop a path, query or fragment ("unifi.local/", "1.2.3.4/manage").
    host = re.split(r"[/?#]", host, maxsplit=1)[0]
    port: str | None = None

    if host.startswith("["):
        # "[fd00::1]" or "[fd00::1]:8443"
        address, bracket, rest = host[1:].partition("]")
        if not bracket or (rest and not rest.startswith(":")):
            return None
        if not is_ipv6_address(address):
            return None  # Brackets are only used around IPv6 addresses.
        host, port = address, rest[1:] if rest else None
    elif host.count(":") == 1:
        # "host:8443"; more than one colon is a bare IPv6 address.
        host, port = host.split(":")

    if port is not None and not (_PORT.match(port) and 1 <= int(port) <= 65535):
        return None
    if not host or not is_host_valid(host):
        return None
    if ":" in host:
        # Store IPv6 addresses in their canonical, compressed form.
        host = str(ip_address(host))
    return host, int(port) if port is not None else None


def _normalize_host(user_input: dict[str, Any]) -> dict[str, str]:
    """Clean up the host in place; return form errors if it is invalid.

    A port given with the host takes precedence over the port field, because
    the user typed it explicitly while the port field is pre-filled with 443.
    """
    parsed = _parse_host(user_input[CONF_HOST])
    if parsed is None:
        return {CONF_HOST: "invalid_host"}
    user_input[CONF_HOST], port = parsed
    if port is not None:
        user_input[CONF_PORT] = port
    return {}


async def _async_fetch_sites(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> tuple[list[UnifiSite], dict[str, str]]:
    """Validate the connection data and return (sites, form errors).

    Uses GET /v1/sites, which also proves that the API key is valid.
    """
    client = async_create_api_client(hass, data)
    try:
        sites = await client.async_get_sites()
    except UnifiInvalidAuth:
        return [], {"base": "invalid_auth"}
    except UnifiApiError as err:
        # Unreachable host, or no UniFi Network API at this address.
        _LOGGER.debug("Validation failed: %s", err)
        return [], {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unexpected exception while validating the API key")
        return [], {"base": "unknown"}
    return sites, {}


async def _async_validate_site(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> dict[str, str]:
    """Validate the connection data and that the configured site still exists."""
    sites, errors = await _async_fetch_sites(hass, data)
    if not errors and all(site.id != data[CONF_SITE_ID] for site in sites):
        errors = {"base": "site_not_found"}
    return errors


class UnifiNetworkExtendedConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UniFi Network Extended.

    One config entry is created per UniFi site; the site ID is the unique ID.
    """

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return UnifiNetworkExtendedOptionsFlow()

    def __init__(self) -> None:
        """Initialize the flow."""
        self._connection: dict[str, Any] = {}
        self._sites: dict[str, UnifiSite] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the connection details."""
        errors: dict[str, str] = {}

        if user_input is not None:
            _strip_input(user_input)
            errors = _normalize_host(user_input)
            sites: list[UnifiSite] = []
            if not errors:
                sites, errors = await _async_fetch_sites(self.hass, user_input)
            if not errors:
                if not sites:
                    return self.async_abort(reason="no_sites")
                self._connection = user_input
                self._sites = {site.id: site for site in sites}
                if len(sites) == 1:
                    return await self._async_create_site_entry(sites[0])
                return await self.async_step_site()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _connection_schema({}), user_input
            ),
            errors=errors,
        )

    async def async_step_site(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick one of several sites."""
        if user_input is not None:
            return await self._async_create_site_entry(
                self._sites[user_input[CONF_SITE_ID]]
            )

        configured = self._async_current_ids(include_ignore=False)
        options = [
            SelectOptionDict(value=site.id, label=site.name)
            for site in sorted(self._sites.values(), key=lambda site: site.name)
            if site.id not in configured
        ]
        if not options:
            return self.async_abort(reason="already_configured")

        return self.async_show_form(
            step_id="site",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SITE_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    async def _async_create_site_entry(self, site: UnifiSite) -> ConfigFlowResult:
        """Create the config entry for the chosen site."""
        await self.async_set_unique_id(site.id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=site.name,
            data={**self._connection, CONF_SITE_ID: site.id},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow changing host, port, API key and SSL option via the UI.

        The site itself cannot be changed; add a new entry for another site.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            _strip_input(user_input)
            errors = _normalize_host(user_input)
            if not errors:
                errors = await _async_validate_site(
                    self.hass, {**user_input, CONF_SITE_ID: entry.data[CONF_SITE_ID]}
                )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reconfigure",
            # Show the user's last input again so a typo can be corrected.
            data_schema=self.add_suggested_values_to_schema(
                _connection_schema(entry.data), user_input
            ),
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
            errors = await _async_validate_site(self.hass, {**entry.data, **user_input})
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): API_KEY_SELECTOR}),
            description_placeholders={CONF_HOST: entry.data[CONF_HOST]},
            errors=errors,
        )


def _interval_selector(minimum: int) -> vol.All:
    return vol.All(
        NumberSelector(
            NumberSelectorConfig(
                min=minimum,
                max=3600,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        ),
        vol.Coerce(int),
    )


class UnifiNetworkExtendedOptionsFlow(OptionsFlowWithReload):
    """Options: polling intervals and client tracking.

    Home Assistant reloads the entry once when the options changed, so a new
    interval or client tracking takes effect right away.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): _interval_selector(10),
                    vol.Required(
                        CONF_STATISTICS_INTERVAL,
                        default=options.get(
                            CONF_STATISTICS_INTERVAL, DEFAULT_STATISTICS_INTERVAL
                        ),
                    ): _interval_selector(30),
                    vol.Required(
                        CONF_TRACK_CLIENTS,
                        default=options.get(CONF_TRACK_CLIENTS, DEFAULT_TRACK_CLIENTS),
                    ): bool,
                }
            ),
        )
