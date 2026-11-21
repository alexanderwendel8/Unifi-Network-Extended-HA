"""Client for the official UniFi Network API (Integration API).

Only endpoints from the official OpenAPI specification in
``docs/unifi-network-api.openapi.json`` may be used here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
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


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp of the API, None if missing."""
    return dt_util.parse_datetime(value) if value else None


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
    interfaces: frozenset[str] = frozenset()  # "ports" and/or "radios"

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
            interfaces=frozenset(data.get("interfaces", ())),
        )


@dataclass(frozen=True, slots=True)
class UnifiPortPoe:
    """PoE details of a port ("Port PoE overview")."""

    enabled: bool
    state: str  # UP, DOWN, LIMITED or UNKNOWN
    standard: str  # 802.3af, 802.3at or 802.3bt
    type: int  # 1-4


@dataclass(frozen=True, slots=True)
class UnifiPort:
    """A physical port of a device ("Port overview")."""

    idx: int
    state: str  # UP, DOWN or UNKNOWN
    connector: str  # RJ45, SFP, SFPPLUS, SFP28 or QSFP28
    max_speed_mbps: int
    speed_mbps: int | None
    poe: UnifiPortPoe | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> UnifiPort:
        """Create from a "Port overview" object."""
        poe = data.get("poe")
        return cls(
            idx=data["idx"],
            state=data["state"],
            connector=data["connector"],
            max_speed_mbps=data["maxSpeedMbps"],
            speed_mbps=data.get("speedMbps"),
            poe=(
                UnifiPortPoe(
                    enabled=poe["enabled"],
                    state=poe["state"],
                    standard=poe["standard"],
                    type=int(poe["type"]),
                )
                if poe
                else None
            ),
        )


def radio_band(frequency_ghz: float) -> str:
    """Return the band key of a radio frequency, e.g. 2.4 -> "2.4", 5.0 -> "5"."""
    return f"{frequency_ghz:g}"


@dataclass(frozen=True, slots=True)
class UnifiRadio:
    """A wireless radio of an access point ("Wireless radio overview")."""

    frequency_ghz: float  # 2.4, 5, 6 or 60
    wlan_standard: str  # 802.11a/b/g/n/ac/ax/be
    channel_width_mhz: int
    channel: int | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> UnifiRadio:
        """Create from a "Wireless radio overview" object."""
        return cls(
            frequency_ghz=data["frequencyGHz"],
            wlan_standard=data["wlanStandard"],
            channel_width_mhz=data["channelWidthMHz"],
            channel=data.get("channel"),
        )


@dataclass(frozen=True, slots=True)
class UnifiDeviceDetails:
    """Details of an adopted device ("Adopted device details")."""

    ports: dict[int, UnifiPort]
    uplink_device_id: str | None
    provisioned_at: datetime | None
    adopted_at: datetime | None
    # Wireless radios keyed by band (see radio_band), access points only.
    radios: dict[str, UnifiRadio] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> UnifiDeviceDetails:
        """Create from an "Adopted device details" object."""
        interfaces = data.get("interfaces") or {}
        ports = interfaces.get("ports") or []
        radios = interfaces.get("radios") or []
        return cls(
            radios={
                radio_band(radio["frequencyGHz"]): UnifiRadio.from_api(radio)
                for radio in radios
            },
            ports={port["idx"]: UnifiPort.from_api(port) for port in ports},
            uplink_device_id=(data.get("uplink") or {}).get("deviceId"),
            provisioned_at=_parse_datetime(data.get("provisionedAt")),
            adopted_at=_parse_datetime(data.get("adoptedAt")),
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
            connected_at=_parse_datetime(connected_at),
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
    # TX retries in percent per radio band (see radio_band), access points only.
    radio_tx_retries_pct: dict[str, float | None] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> UnifiDeviceStatistics:
        """Create from a "Latest statistics for a device" object."""
        uplink = data.get("uplink") or {}
        radios = (data.get("interfaces") or {}).get("radios") or []
        return cls(
            uptime_sec=data.get("uptimeSec"),
            cpu_utilization_pct=data.get("cpuUtilizationPct"),
            memory_utilization_pct=data.get("memoryUtilizationPct"),
            load_average_1min=data.get("loadAverage1Min"),
            load_average_5min=data.get("loadAverage5Min"),
            load_average_15min=data.get("loadAverage15Min"),
            uplink_rx_rate_bps=uplink.get("rxRateBps"),
            uplink_tx_rate_bps=uplink.get("txRateBps"),
            radio_tx_retries_pct={
                radio_band(radio["frequencyGHz"]): radio.get("txRetriesPct")
                for radio in radios
            },
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

    async def async_restart_device(self, site_id: str, device_id: str) -> None:
        """Restart an adopted device.

        ``POST /v1/sites/{siteId}/devices/{deviceId}/actions``
        with the "Device restart request" body ``{"action": "RESTART"}``.
        """
        await self._request(
            "POST",
            f"/v1/sites/{site_id}/devices/{device_id}/actions",
            json={"action": "RESTART"},
            expect_body=False,
        )

    async def async_get_device_details(
        self, site_id: str, device_id: str
    ) -> UnifiDeviceDetails:
        """Return the details of an adopted device (ports, radios, uplink, ...).

        ``GET /v1/sites/{siteId}/devices/{deviceId}`` ("Adopted device details").
        """
        return UnifiDeviceDetails.from_api(
            await self._request("GET", f"/v1/sites/{site_id}/devices/{device_id}")
        )

    async def async_power_cycle_port(
        self, site_id: str, device_id: str, port_idx: int
    ) -> None:
        """Power-cycle PoE on a port.

        ``POST /v1/sites/{siteId}/devices/{deviceId}``
        ``/interfaces/ports/{portIdx}/actions`` with the
        "Port PoE power-cycle request" body ``{"action": "POWER_CYCLE"}``.
        """
        await self._request(
            "POST",
            f"/v1/sites/{site_id}/devices/{device_id}/interfaces/ports/{port_idx}"
            "/actions",
            json={"action": "POWER_CYCLE"},
            expect_body=False,
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
        expect_body: bool = True,
    ) -> Any:
        """Send a request and return the decoded JSON body.

        With ``expect_body=False`` the body is ignored (e.g. actions that only
        answer with HTTP 200 and no documented content).
        """
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
                if response.status == 204 or not expect_body:
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
