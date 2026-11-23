"""Client for the official UniFi Network API (Integration API).

Only endpoints from the official OpenAPI specification in
``docs/unifi-network-api.openapi.json`` may be used here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any

import aiohttp
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from yarl import URL

_LOGGER = logging.getLogger(__name__)

API_BASE_PATH = "/proxy/network/integration"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
PAGE_LIMIT = 200  # Maximum page size allowed by the API.


# Gets the cause of a skipped entry, e.g. "port skipped: field 'idx' is missing".
type InvalidEntryCallback = Callable[[str], None]


class InvalidFieldError(ValueError):
    """A field of an API object is missing or has an unexpected type.

    The message names the field, never its value: values can contain personal
    data such as client names or MAC addresses.
    """


def _check_type(field_name: str, value: Any, expected: type | tuple[type, ...]) -> Any:
    """Return the value if it has the expected type (bool is no number)."""
    if not isinstance(value, expected) or (
        isinstance(value, bool)
        and bool not in (expected if isinstance(expected, tuple) else (expected,))
    ):
        raise InvalidFieldError(f"field '{field_name}' has an unexpected type")
    return value


def _object(value: Any, name: str = "response") -> Mapping[str, Any]:
    """Return the value if it is a JSON object."""
    if not isinstance(value, Mapping):
        raise InvalidFieldError(f"{name} is not an object")
    return value


def _required(
    data: Mapping[str, Any], key: str, expected: type | tuple[type, ...]
) -> Any:
    """Return a field that is required in the specification."""
    if data.get(key) is None:
        raise InvalidFieldError(f"field '{key}' is missing")
    return _check_type(key, data[key], expected)


def _optional(
    data: Mapping[str, Any], key: str, expected: type | tuple[type, ...]
) -> Any:
    """Return an optional field of the specification, None if missing."""
    value = data.get(key)
    return None if value is None else _check_type(key, value, expected)


_NUMBER = (int, float)


def _parse_datetime(data: Mapping[str, Any], key: str) -> datetime | None:
    """Parse an optional ISO 8601 timestamp of the API, None if missing."""
    value = _optional(data, key, str)
    return dt_util.parse_datetime(value) if value else None


def _describe_parse_error(err: Exception) -> str:
    """Describe a parse error without the values of the response."""
    if isinstance(err, InvalidFieldError):
        return str(err)
    if isinstance(err, KeyError):
        return "a required field is missing"
    return f"unexpected value ({type(err).__name__})"


# Errors raised while reading API objects: missing fields, unexpected types or values.
_PARSE_ERRORS = (KeyError, TypeError, ValueError)


def _parse_entries[T](
    entries: Iterable[Any],
    parse: Callable[[Mapping[str, Any]], T],
    kind: str,
    on_invalid: InvalidEntryCallback | None,
    skipped_ids: set[str] | None = None,
) -> list[T]:
    """Parse every entry of a list, skipping (and reporting) invalid ones.

    If given, ``skipped_ids`` receives the ``id`` of every skipped entry that
    has one, so callers can tell "invalid" apart from "no longer reported".
    """
    result: list[T] = []
    for entry in entries:
        try:
            result.append(parse(_object(entry, kind)))
        except _PARSE_ERRORS as err:
            if (
                skipped_ids is not None
                and isinstance(entry, Mapping)
                and isinstance(entry_id := entry.get("id"), str)
            ):
                skipped_ids.add(entry_id)
            cause = f"{kind} skipped: {_describe_parse_error(err)}"
            if on_invalid is None:
                _LOGGER.debug("Invalid entry in API response, %s", cause)
            else:
                on_invalid(cause)
    return result


class UnifiApiError(Exception):
    """Base error for the UniFi API client."""


class UnifiCannotConnect(UnifiApiError):
    """Raised when the controller cannot be reached."""


class UnifiInvalidAuth(UnifiApiError):
    """Raised when the API key is missing, invalid or lacks permissions."""


class UnifiResponseError(UnifiApiError):
    """Raised when a response cannot be read (invalid JSON, unexpected content)."""


@dataclass(frozen=True, slots=True)
class UnifiSite:
    """A local site (``GET /v1/sites``)."""

    id: str
    name: str
    internal_reference: str

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> UnifiSite:
        """Create from a "Site overview" object."""
        return cls(
            id=_required(data, "id", str),
            name=_required(data, "name", str),
            internal_reference=_required(data, "internalReference", str),
        )


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
        """Create from an "Adopted device overview" object.

        ``features`` and ``interfaces`` are required in the specification but
        only used as sets, so a missing list is read as empty.
        """
        return cls(
            id=_required(data, "id", str),
            name=_required(data, "name", str),
            model=_required(data, "model", str),
            mac_address=_required(data, "macAddress", str),
            ip_address=_required(data, "ipAddress", str),
            state=_required(data, "state", str),
            firmware_version=_optional(data, "firmwareVersion", str) or "",
            firmware_updatable=_required(data, "firmwareUpdatable", bool),
            features=_string_set(data, "features"),
            interfaces=_string_set(data, "interfaces"),
        )


def _string_set(data: Mapping[str, Any], key: str) -> frozenset[str]:
    """Read an optional list of strings as a set."""
    values = _optional(data, key, list) or []
    return frozenset(_check_type(key, value, str) for value in values)


@dataclass(frozen=True, slots=True)
class UnifiPortPoe:
    """PoE details of a port ("Port PoE overview")."""

    enabled: bool
    state: str  # UP, DOWN, LIMITED or UNKNOWN
    standard: str  # 802.3af, 802.3at or 802.3bt
    type: int  # 1-4

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> UnifiPortPoe:
        """Create from a "Port PoE overview" object."""
        return cls(
            enabled=_required(data, "enabled", bool),
            state=_required(data, "state", str),
            standard=_required(data, "standard", str),
            # Integer enum 1-4; int() also accepts the value as a string.
            type=int(_required(data, "type", (int, str))),
        )


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
        poe = _optional(data, "poe", Mapping)
        return cls(
            idx=_required(data, "idx", int),
            state=_required(data, "state", str),
            connector=_required(data, "connector", str),
            max_speed_mbps=_required(data, "maxSpeedMbps", int),
            speed_mbps=_optional(data, "speedMbps", int),
            poe=UnifiPortPoe.from_api(poe) if poe else None,
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
            frequency_ghz=_required(data, "frequencyGHz", _NUMBER),
            wlan_standard=_required(data, "wlanStandard", str),
            channel_width_mhz=_required(data, "channelWidthMHz", int),
            channel=_optional(data, "channel", int),
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
    def from_api(
        cls,
        data: Mapping[str, Any],
        on_invalid: InvalidEntryCallback | None = None,
    ) -> UnifiDeviceDetails:
        """Create from an "Adopted device details" object.

        Invalid ports and radios are skipped and reported to ``on_invalid``.
        """
        data = _object(data)
        interfaces = _optional(data, "interfaces", Mapping) or {}
        ports = _parse_entries(
            _optional(interfaces, "ports", list) or [],
            UnifiPort.from_api,
            "port",
            on_invalid,
        )
        radios = _parse_entries(
            _optional(interfaces, "radios", list) or [],
            UnifiRadio.from_api,
            "radio",
            on_invalid,
        )
        uplink = _optional(data, "uplink", Mapping) or {}
        return cls(
            radios={radio_band(radio.frequency_ghz): radio for radio in radios},
            ports={port.idx: port for port in ports},
            uplink_device_id=_optional(uplink, "deviceId", str),
            provisioned_at=_parse_datetime(data, "provisionedAt"),
            adopted_at=_parse_datetime(data, "adoptedAt"),
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
        """Create from a "Client overview" object.

        ``access`` is required in the specification, but only its optional
        ``type`` is used, so a missing object is read as an unknown type.
        """
        return cls(
            id=_required(data, "id", str),
            name=_required(data, "name", str),
            type=_required(data, "type", str),
            mac_address=_optional(data, "macAddress", str),
            ip_address=_optional(data, "ipAddress", str),
            connected_at=_parse_datetime(data, "connectedAt"),
            uplink_device_id=_optional(data, "uplinkDeviceId", str),
            access_type=_optional(
                _optional(data, "access", Mapping) or {}, "type", str
            ),
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
    # Time of the last heartbeat, the uptime refers to this moment.
    last_heartbeat_at: datetime | None = None

    @classmethod
    def from_api(
        cls,
        data: Mapping[str, Any],
        on_invalid: InvalidEntryCallback | None = None,
    ) -> UnifiDeviceStatistics:
        """Create from a "Latest statistics for a device" object.

        Invalid radios are skipped and reported to ``on_invalid``.
        """
        data = _object(data)
        uplink = _optional(data, "uplink", Mapping) or {}
        interfaces = _optional(data, "interfaces", Mapping) or {}
        radios = _parse_entries(
            _optional(interfaces, "radios", list) or [],
            _radio_tx_retries,
            "radio",
            on_invalid,
        )
        return cls(
            uptime_sec=_optional(data, "uptimeSec", int),
            cpu_utilization_pct=_optional(data, "cpuUtilizationPct", _NUMBER),
            memory_utilization_pct=_optional(data, "memoryUtilizationPct", _NUMBER),
            load_average_1min=_optional(data, "loadAverage1Min", _NUMBER),
            load_average_5min=_optional(data, "loadAverage5Min", _NUMBER),
            load_average_15min=_optional(data, "loadAverage15Min", _NUMBER),
            uplink_rx_rate_bps=_optional(uplink, "rxRateBps", int),
            uplink_tx_rate_bps=_optional(uplink, "txRateBps", int),
            radio_tx_retries_pct=dict(radios),
            last_heartbeat_at=_parse_datetime(data, "lastHeartbeatAt"),
        )


def _radio_tx_retries(data: Mapping[str, Any]) -> tuple[str, float | None]:
    """Read band and TX retries of a "Latest statistics for wireless radio"."""
    return (
        radio_band(_required(data, "frequencyGHz", _NUMBER)),
        _optional(data, "txRetriesPct", _NUMBER),
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
        # yarl puts IPv6 addresses in brackets (https://[fd00::1]:443/...).
        self._base_url = str(
            URL.build(scheme="https", host=host, port=port, path=API_BASE_PATH)
        )
        self._headers = {"X-API-KEY": api_key, "Accept": "application/json"}
        # Causes of invalid response data that were already logged as warning.
        self._reported_causes: set[tuple[str, str]] = set()

    def _report_invalid(self, endpoint: str, cause: str) -> None:
        """Log invalid response data, as warning only once per cause.

        ``endpoint`` is the path template of the specification and ``cause``
        names the field, so neither contains IDs, names, MAC addresses or the
        host.
        """
        if (endpoint, cause) in self._reported_causes:
            _LOGGER.debug("Unexpected data from %s: %s", endpoint, cause)
            return
        self._reported_causes.add((endpoint, cause))
        _LOGGER.warning(
            "Unexpected data from the UniFi Network API (%s): %s. This message is "
            "logged only once",
            endpoint,
            cause,
        )

    def _parse_object[T](
        self,
        endpoint: str,
        data: Any,
        parse: Callable[[Mapping[str, Any], InvalidEntryCallback], T],
    ) -> T:
        """Parse a single object; invalid entries of its lists are skipped."""

        def on_invalid(cause: str) -> None:
            self._report_invalid(endpoint, cause)

        try:
            return parse(_object(data), on_invalid)
        except _PARSE_ERRORS as err:
            cause = _describe_parse_error(err)
            self._report_invalid(endpoint, cause)
            raise UnifiResponseError(
                f"Unexpected response from {endpoint}: {cause}"
            ) from err

    async def _async_get_list[T](
        self,
        path: str,
        endpoint: str,
        parse: Callable[[Mapping[str, Any]], T],
        kind: str,
        skipped_ids: set[str] | None = None,
    ) -> list[T]:
        """Fetch all pages of a list endpoint and parse every entry.

        Invalid entries are skipped, so a single unexpected object (e.g. a new
        device type) does not break the whole list.
        """
        return _parse_entries(
            await self._get_all_pages(path, endpoint),
            parse,
            kind,
            lambda cause: self._report_invalid(endpoint, cause),
            skipped_ids,
        )

    async def async_get_application_version(self) -> str:
        """Return the Network application version (``GET /v1/info``)."""
        return self._parse_object(
            "/v1/info",
            await self._request("GET", "/v1/info"),
            lambda data, _: _required(data, "applicationVersion", str),
        )

    async def async_get_sites(self) -> list[UnifiSite]:
        """Return all local sites (``GET /v1/sites``)."""
        return await self._async_get_list(
            "/v1/sites", "/v1/sites", UnifiSite.from_api, "site"
        )

    async def async_get_devices(
        self, site_id: str, *, skipped_ids: set[str] | None = None
    ) -> list[UnifiDevice]:
        """Return all adopted devices (``GET /v1/sites/{siteId}/devices``).

        ``skipped_ids`` receives the IDs of devices that UniFi reports but that
        were skipped because their data is invalid.
        """
        return await self._async_get_list(
            f"/v1/sites/{site_id}/devices",
            "/v1/sites/{siteId}/devices",
            UnifiDevice.from_api,
            "device",
            skipped_ids,
        )

    async def async_get_clients(self, site_id: str) -> list[UnifiClient]:
        """Return all connected clients (``GET /v1/sites/{siteId}/clients``)."""
        return await self._async_get_list(
            f"/v1/sites/{site_id}/clients",
            "/v1/sites/{siteId}/clients",
            UnifiClient.from_api,
            "client",
        )

    async def async_get_device_statistics(
        self, site_id: str, device_id: str
    ) -> UnifiDeviceStatistics:
        """Return the latest statistics of a device.

        ``GET /v1/sites/{siteId}/devices/{deviceId}/statistics/latest``
        """
        return self._parse_object(
            "/v1/sites/{siteId}/devices/{deviceId}/statistics/latest",
            await self._request(
                "GET", f"/v1/sites/{site_id}/devices/{device_id}/statistics/latest"
            ),
            UnifiDeviceStatistics.from_api,
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
        return self._parse_object(
            "/v1/sites/{siteId}/devices/{deviceId}",
            await self._request("GET", f"/v1/sites/{site_id}/devices/{device_id}"),
            UnifiDeviceDetails.from_api,
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

    async def _get_all_pages(self, path: str, endpoint: str) -> list[Any]:
        """Fetch every page of a paginated list endpoint (offset/limit).

        Returns the raw entries; ``endpoint`` is the path template for messages.
        """
        items: list[Any] = []
        offset = 0
        while True:
            page = await self._request(
                "GET", path, params={"offset": offset, "limit": PAGE_LIMIT}
            )
            data, count, total_count = self._parse_object(
                endpoint,
                page,
                lambda page, _: (
                    _required(page, "data", list),
                    _required(page, "count", int),
                    _required(page, "totalCount", int),
                ),
            )
            items.extend(data)
            offset += count
            if count == 0 or offset >= total_count:
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
                try:
                    return await response.json()
                except (aiohttp.ContentTypeError, ValueError) as err:
                    # Reachable, but no JSON (e.g. an HTML page or a cut-off body).
                    # The body is not logged, it could contain personal data.
                    raise UnifiResponseError(
                        f"{method} {path}: the response is not valid JSON"
                    ) from err
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
