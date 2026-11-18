"""Minimal API client for a UniFi Network controller."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from typing import Any

import aiohttp

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)


class UnifiApiError(Exception):
    """Base error for the UniFi API client."""


class UnifiCannotConnect(UnifiApiError):
    """Raised when the controller cannot be reached."""


class UnifiInvalidAuth(UnifiApiError):
    """Raised when the credentials are rejected."""


class UnifiApiClient:
    """Small client used to authenticate against a UniFi controller.

    SSL verification is configured on the passed ClientSession.

    Supports UniFi OS consoles (UDM, UCG, Cloud Key Gen2+, ...) and the
    classic self-hosted Network application.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = f"https://{host}:{port}"
        self._username = username
        self._password = password
        self.is_unifi_os: bool | None = None

    async def login(self) -> None:
        """Authenticate against the controller.

        Raises UnifiInvalidAuth or UnifiCannotConnect on failure.
        """
        payload = {
            "username": self._username,
            "password": self._password,
            "remember": True,
        }

        # UniFi OS first, then the classic controller endpoint.
        for is_unifi_os, path in ((True, "/api/auth/login"), (False, "/api/login")):
            status = await self._post(path, payload)
            if status == 200:
                self.is_unifi_os = is_unifi_os
                return
            if status in (400, 401, 403):
                raise UnifiInvalidAuth
            # 404 -> endpoint does not exist on this controller type, try next.

        raise UnifiCannotConnect

    async def _post(self, path: str, payload: dict[str, Any]) -> int:
        """Send a POST request and return the HTTP status code."""
        try:
            async with self._session.post(
                f"{self._base_url}{path}",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                return response.status
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            # Never include the payload (password) in logs.
            _LOGGER.debug("Error connecting to %s%s: %s", self._base_url, path, err)
            raise UnifiCannotConnect from err


def async_create_api_client(hass: HomeAssistant, data: Mapping[str, Any]) -> UnifiApiClient:
    """Create an API client with its own session for the given config data.

    A dedicated session is used so the controller's auth cookie is not shared
    with other integrations. ``unsafe=True`` allows cookies for IP hosts.
    """
    session = async_create_clientsession(
        hass,
        verify_ssl=data[CONF_VERIFY_SSL],
        cookie_jar=aiohttp.CookieJar(unsafe=True),
    )
    return UnifiApiClient(
        session=session,
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
    )
