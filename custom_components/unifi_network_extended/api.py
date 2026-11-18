"""Client for the official UniFi Network API (Integration API).

Only endpoints from the official OpenAPI specification in
``docs/unifi-network-api.openapi.json`` may be used here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

import aiohttp
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

API_BASE_PATH = "/proxy/network/integration"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
PAGE_LIMIT = 200  # Maximum page size allowed by the API.


class UnifiApiError(Exception):
    """Base error for the UniFi API client."""


class UnifiCannotConnect(UnifiApiError):
    """Raised when the controller cannot be reached."""


class UnifiInvalidAuth(UnifiApiError):
    """Raised when the API key is missing, invalid or lacks permissions."""


@dataclass(frozen=True, slots=True)
class UnifiSite:
    """A local site (``GET /v1/sites``)."""

    id: str
    name: str
    internal_reference: str


@dataclass(frozen=True, slots=True)
class UnifiDevice:
    """An adopted device (``GET /v1/sites/{siteId}/devices``)."""

    id: str
    name: str
    model: str
    mac_address: str
    ip_address: str
    state: str
    firmware_version: str
    firmware_updatable: bool
    features: frozenset[str]

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> UnifiDevice:
        """Create from an "Adopted device overview" object."""
        return cls(
            id=data["id"],
            name=data["name"],
            model=data["model"],
            mac_address=data["macAddress"],
            ip_address=data["ipAddress"],
            state=data["state"],
            firmware_version=data.get("firmwareVersion", ""),
            firmware_updatable=data["firmwareUpdatable"],
            features=frozenset(data.get("features", ())),
        )


@dataclass(frozen=True, slots=True)
class UnifiClient:
    """A connected client (``GET /v1/sites/{siteId}/clients``)."""

    id: str
    name: str
    type: str  # WIRED, WIRELESS, VPN or TELEPORT
    mac_address: str | None
    ip_address: str | None
    connected_at: datetime | None
    uplink_device_id: str | None
    access_type: str | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> UnifiClient:
        """Create from a "Client overview" object."""
        connected_at = data.get("connectedAt")
        return cls(
            id=data["id"],
            name=data["name"],
            type=data["type"],
            mac_address=data.get("macAddress"),
            ip_address=data.get("ipAddress"),
            connected_at=dt_util.parse_datetime(connected_at) if connected_at else None,
            uplink_device_id=data.get("uplinkDeviceId"),
            access_type=(data.get("access") or {}).get("type"),
        )


@dataclass(frozen=True, slots=True)
class UnifiDeviceStatistics:
    """Latest device statistics (``.../devices/{deviceId}/statistics/latest``).

    All values are optional in the specification.
    """

    uptime_sec: int | None
    cpu_utilization_pct: float | None
    memory_utilization_pct: float | None
    load_average_1min: float | None
    load_average_5min: float | None
    load_average_15min: float | None
    uplink_rx_rate_bps: int | None
    uplink_tx_rate_bps: int | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> UnifiDeviceStatistics:
        """Create from a "Latest statistics for a device" object."""
        uplink = data.get("uplink") or {}
        return cls(
            uptime_sec=data.get("uptimeSec"),
            cpu_utilization_pct=data.get("cpuUtilizationPct"),
            memory_utilization_pct=data.get("memoryUtilizationPct"),
            load_average_1min=data.get("loadAverage1Min"),
            load_average_5min=data.get("loadAverage5Min"),
            load_average_15min=data.get("loadAverage15Min"),
            uplink_rx_rate_bps=uplink.get("rxRateBps"),
            uplink_tx_rate_bps=uplink.get("txRateBps"),
        )


class UnifiApiClient:
    """Client for the official UniFi Network API.

    Authentication uses an API key sent in the ``X-API-KEY`` header.
    SSL verification is configured on the passed ClientSession.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        api_key: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = f"https://{host}:{port}{API_BASE_PATH}"
        self._headers = {"X-API-KEY": api_key, "Accept": "application/json"}

    async def async_get_application_version(self) -> str:
        """Return the Network application version (``GET /v1/info``)."""
        data = await self._request("GET", "/v1/info")
        return data["applicationVersion"]

    async def async_get_sites(self) -> list[UnifiSite]:
        """Return all local sites (``GET /v1/sites``)."""
        return [
            UnifiSite(
                id=item["id"],
                name=item["name"],
                internal_reference=item["internalReference"],
            )
            for item in await self._get_all_pages("/v1/sites")
        ]

    async def async_get_devices(self, site_id: str) -> list[UnifiDevice]:
        """Return all adopted devices (``GET /v1/sites/{siteId}/devices``)."""
        return [
            UnifiDevice.from_api(item)
            for item in await self._get_all_pages(f"/v1/sites/{site_id}/devices")
        ]

    async def async_get_clients(self, site_id: str) -> list[UnifiClient]:
        """Return all connected clients (``GET /v1/sites/{siteId}/clients``)."""
        return [
            UnifiClient.from_api(item)
            for item in await self._get_all_pages(f"/v1/sites/{site_id}/clients")
        ]

    async def async_get_device_statistics(
        self, site_id: str, device_id: str
    ) -> UnifiDeviceStatistics:
        """Return the latest statistics of a device.

        ``GET /v1/sites/{siteId}/devices/{deviceId}/statistics/latest``
        """
        return UnifiDeviceStatistics.from_api(
            await self._request(
                "GET", f"/v1/sites/{site_id}/devices/{device_id}/statistics/latest"
            )
        )

    async def _get_all_pages(self, path: str) -> list[dict[str, Any]]:
        """Fetch every page of a paginated list endpoint (offset/limit)."""
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self._request(
                "GET", path, params={"offset": offset, "limit": PAGE_LIMIT}
            )
            items.extend(page["data"])
            offset += page["count"]
            if page["count"] == 0 or offset >= page["totalCount"]:
                return items

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Send a request and return the decoded JSON body."""
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                headers=self._headers,
                params=params,
                json=json,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    raise UnifiInvalidAuth(
                        f"HTTP {response.status}: {await _error_message(response)}"
                    )
                if response.status >= 400:
                    raise UnifiApiError(
                        f"{method} {path} failed with HTTP {response.status}: "
                        f"{await _error_message(response)}"
                    )
                if response.status == 204:
                    return None
                return await response.json()
        except (TimeoutError, aiohttp.ClientError) as err:
            # Headers (API key) are never logged.
            _LOGGER.debug("Error requesting %s %s: %s", method, path, err)
            raise UnifiCannotConnect from err


async def _error_message(response: aiohttp.ClientResponse) -> str:
    """Extract the message from the API's standard error body, if present."""
    try:
        body = await response.json(content_type=None)
    except (aiohttp.ClientError, ValueError):
        return ""
    if isinstance(body, dict):
        return f"{body.get('code', '')} {body.get('message', '')}".strip()
    return ""


def async_create_api_client(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> UnifiApiClient:
    """Create an API client for the given config entry data."""
    return UnifiApiClient(
        session=async_get_clientsession(hass, verify_ssl=data[CONF_VERIFY_SSL]),
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        api_key=data[CONF_API_KEY],
    )
