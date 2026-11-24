"""Tests for the official UniFi Network API client."""

import logging
from unittest.mock import patch

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.unifi_network_extended.api import (
    UnifiApiClient,
    UnifiApiError,
    UnifiCannotConnect,
    UnifiInvalidAuth,
    UnifiResponseError,
    UnifiSite,
)

BASE = "https://192.168.1.1:443/proxy/network/integration"


def _client(hass: HomeAssistant) -> UnifiApiClient:
    return UnifiApiClient(async_get_clientsession(hass), "192.168.1.1", 443, "key")


async def test_get_info_sends_api_key(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """GET /v1/info returns the version and sends the X-API-KEY header."""
    aioclient_mock.get(f"{BASE}/v1/info", json={"applicationVersion": "10.3.58"})

    assert await _client(hass).async_get_application_version() == "10.3.58"
    _, _, _, headers = aioclient_mock.mock_calls[0]
    assert headers["X-API-KEY"] == "key"


@pytest.mark.parametrize(
    ("host", "port", "url"),
    [
        ("unifi.local", 443, "https://unifi.local:443/proxy/network/integration"),
        ("192.168.1.1", 443, "https://192.168.1.1:443/proxy/network/integration"),
        ("fd00::1", 443, "https://[fd00::1]:443/proxy/network/integration"),
        ("fd00::1", 8443, "https://[fd00::1]:8443/proxy/network/integration"),
    ],
)
async def test_base_url(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    host: str,
    port: int,
    url: str,
) -> None:
    """Hostnames, IPv4 and IPv6 addresses (in brackets) form a valid URL."""
    aioclient_mock.get(
        f"{url}/v1/sites",
        json={"offset": 0, "limit": 200, "count": 0, "totalCount": 0, "data": []},
    )
    client = UnifiApiClient(async_get_clientsession(hass), host, port, "key")

    assert await client.async_get_sites() == []
    _, called, _, _ = aioclient_mock.mock_calls[0]
    expected = URL(f"{url}/v1/sites")
    # Compare the parts: yarl omits the default port 443 when printing a URL.
    assert called.scheme == "https"
    assert called.raw_host == expected.raw_host
    assert called.port == port
    assert called.path == "/proxy/network/integration/v1/sites"
    assert called.query == {"offset": "0", "limit": "200"}
    if ":" in host:
        assert called.human_repr().startswith(f"https://[{host}]")


async def test_get_sites_paginates(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """GET /v1/sites follows offset/limit pagination until totalCount."""
    site = {"id": "s1", "name": "Default", "internalReference": "default"}
    aioclient_mock.get(
        f"{BASE}/v1/sites?offset=0&limit=200",
        json={"data": [site], "offset": 0, "count": 1, "limit": 200, "totalCount": 2},
    )
    aioclient_mock.get(
        f"{BASE}/v1/sites?offset=1&limit=200",
        json={
            "data": [{**site, "id": "s2", "name": "Office"}],
            "offset": 1,
            "count": 1,
            "limit": 200,
            "totalCount": 2,
        },
    )

    assert await _client(hass).async_get_sites() == [
        UnifiSite("s1", "Default", "default"),
        UnifiSite("s2", "Office", "default"),
    ]


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        (
            {"status": 401, "json": {"code": "api.authentication.missing-credentials"}},
            UnifiInvalidAuth,
        ),
        ({"status": 403}, UnifiInvalidAuth),
        ({"status": 404}, UnifiApiError),
        ({"status": 500}, UnifiApiError),
        ({"exc": aiohttp.ClientError()}, UnifiCannotConnect),
        ({"exc": TimeoutError()}, UnifiCannotConnect),
    ],
)
async def test_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict,
    error: type[Exception],
) -> None:
    """HTTP and connection errors are mapped to client exceptions."""
    aioclient_mock.get(f"{BASE}/v1/info", **kwargs)
    with pytest.raises(error):
        await _client(hass).async_get_application_version()


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (TimeoutError(), "GET /v1/info: cannot connect (timeout)"),
        (
            aiohttp.ClientConnectionError("Cannot connect to host 192.168.1.1:443"),
            "GET /v1/info: cannot connect (ClientConnectionError)",
        ),
    ],
)
async def test_cannot_connect_message(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    exc: Exception,
    message: str,
) -> None:
    """Connection errors name the request and error type, never the host."""
    aioclient_mock.get(f"{BASE}/v1/info", exc=exc)
    with pytest.raises(UnifiCannotConnect) as err:
        await _client(hass).async_get_application_version()
    assert str(err.value) == message


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        # Standard error body of the API: code and message are passed on.
        (
            {"json": {"code": "api.err.Invalid", "message": "Invalid value"}},
            "HTTP 400: api.err.Invalid Invalid value",
        ),
        # Anything else is ignored instead of failing on it.
        ({"json": ["unexpected"]}, "HTTP 400: "),
        ({"text": "<html>Bad Request</html>"}, "HTTP 400: "),
    ],
)
async def test_error_message_from_body(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict,
    message: str,
) -> None:
    """The error message is only taken from the documented error body."""
    aioclient_mock.get(f"{BASE}/v1/info", status=400, **kwargs)
    with pytest.raises(UnifiApiError) as err:
        await _client(hass).async_get_application_version()
    assert str(err.value).endswith(message)


async def test_get_devices_clients_statistics(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Devices, clients and statistics are parsed from the API responses."""
    page = {"offset": 0, "count": 1, "limit": 200, "totalCount": 1}
    aioclient_mock.get(
        f"{BASE}/v1/sites/s1/devices?offset=0&limit=200",
        json={
            **page,
            "data": [
                {
                    "id": "d1",
                    "name": "Gateway",
                    "model": "UCG Ultra",
                    "macAddress": "aa:bb:cc:00:00:01",
                    "ipAddress": "192.168.1.1",
                    "state": "ONLINE",
                    "firmwareVersion": "4.1.13",
                    "firmwareUpdatable": True,
                    "features": ["gateway"],
                    "interfaces": [],
                    "supported": True,
                }
            ],
        },
    )
    aioclient_mock.get(
        f"{BASE}/v1/sites/s1/clients?offset=0&limit=200",
        json={
            **page,
            "data": [
                {
                    "id": "c1",
                    "name": "Phone",
                    "type": "WIRELESS",
                    "macAddress": "11:22:33:44:55:66",
                    "ipAddress": "192.168.1.50",
                    "connectedAt": "2026-11-18T08:00:00Z",
                    "uplinkDeviceId": "d1",
                    "access": {"type": "DEFAULT"},
                }
            ],
        },
    )
    aioclient_mock.get(
        f"{BASE}/v1/sites/s1/devices/d1/statistics/latest",
        json={
            "uptimeSec": 100,
            "cpuUtilizationPct": 1.5,
            "uplink": {"rxRateBps": 10, "txRateBps": 20},
            "lastHeartbeatAt": "2026-11-22T10:00:00Z",
            "interfaces": {},
        },
    )
    client = _client(hass)

    (device,) = await client.async_get_devices("s1")
    assert device.name == "Gateway"
    assert device.firmware_updatable is True
    assert device.features == frozenset({"gateway"})

    (unifi_client,) = await client.async_get_clients("s1")
    assert unifi_client.type == "WIRELESS"
    assert unifi_client.connected_at.year == 2026
    assert unifi_client.access_type == "DEFAULT"

    stats = await client.async_get_device_statistics("s1", "d1")
    assert stats.uptime_sec == 100
    assert stats.cpu_utilization_pct == 1.5
    assert stats.memory_utilization_pct is None
    assert stats.uplink_tx_rate_bps == 20
    assert stats.last_heartbeat_at.isoformat() == "2026-11-22T10:00:00+00:00"


async def test_restart_device(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The restart action is posted; the empty 200 response is accepted."""
    aioclient_mock.post(f"{BASE}/v1/sites/s1/devices/d1/actions", status=200)

    await _client(hass).async_restart_device("s1", "d1")

    _, url, body, headers = aioclient_mock.mock_calls[0]
    assert url.path == "/proxy/network/integration/v1/sites/s1/devices/d1/actions"
    assert body == {"action": "RESTART"}
    assert headers["X-API-KEY"] == "key"


async def test_get_device_details(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Ports, uplink and provisioning are read from the device details."""
    aioclient_mock.get(
        f"{BASE}/v1/sites/s1/devices/d1",
        json={
            "id": "d1",
            "name": "Switch",
            "uplink": {"deviceId": "gw"},
            "provisionedAt": "2026-11-20T10:00:00Z",
            "adoptedAt": "2025-05-01T08:00:00Z",
            "interfaces": {
                "ports": [
                    {
                        "idx": 1,
                        "state": "UP",
                        "connector": "RJ45",
                        "maxSpeedMbps": 2500,
                        "speedMbps": 1000,
                        "poe": {
                            "enabled": True,
                            "state": "UP",
                            "standard": "802.3bt",
                            "type": 3,
                        },
                    },
                    {
                        "idx": 9,
                        "state": "DOWN",
                        "connector": "SFPPLUS",
                        "maxSpeedMbps": 10000,
                    },
                ]
            },
        },
    )

    details = await _client(hass).async_get_device_details("s1", "d1")
    ports = details.ports

    assert details.uplink_device_id == "gw"
    assert details.provisioned_at.isoformat() == "2026-11-20T10:00:00+00:00"
    assert details.adopted_at.year == 2025
    assert set(ports) == {1, 9}
    assert ports[1].speed_mbps == 1000
    assert ports[1].poe.enabled is True
    assert ports[1].poe.standard == "802.3bt"
    assert ports[1].poe.type == 3
    assert ports[9].speed_mbps is None
    assert ports[9].poe is None


async def test_get_device_details_minimal(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Devices without ports, uplink or timestamps (e.g. the gateway)."""
    aioclient_mock.get(
        f"{BASE}/v1/sites/s1/devices/d1",
        json={"id": "d1", "interfaces": {"radios": []}},
    )
    details = await _client(hass).async_get_device_details("s1", "d1")
    assert details.ports == {}
    assert details.uplink_device_id is None
    assert details.provisioned_at is None
    assert details.adopted_at is None


async def test_power_cycle_port(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The power-cycle action is posted to the port actions endpoint."""
    aioclient_mock.post(
        f"{BASE}/v1/sites/s1/devices/d1/interfaces/ports/4/actions", status=200
    )

    await _client(hass).async_power_cycle_port("s1", "d1", 4)

    _, url, body, _ = aioclient_mock.mock_calls[0]
    assert url.path == (
        "/proxy/network/integration/v1/sites/s1/devices/d1/interfaces/ports/4/actions"
    )
    assert body == {"action": "POWER_CYCLE"}


async def test_radios_in_details_and_statistics(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Radios are read from the device details and the latest statistics."""
    aioclient_mock.get(
        f"{BASE}/v1/sites/s1/devices/ap",
        json={
            "id": "ap",
            "interfaces": {
                "radios": [
                    {
                        "frequencyGHz": 2.4,
                        "wlanStandard": "802.11ax",
                        "channelWidthMHz": 20,
                        "channel": 6,
                    },
                    {
                        "frequencyGHz": 6,
                        "wlanStandard": "802.11be",
                        "channelWidthMHz": 320,
                    },
                ]
            },
        },
    )
    aioclient_mock.get(
        f"{BASE}/v1/sites/s1/devices/ap/statistics/latest",
        json={
            "interfaces": {
                "radios": [
                    {"frequencyGHz": 2.4, "txRetriesPct": 12.5},
                    {"frequencyGHz": 6},
                ]
            }
        },
    )
    client = _client(hass)

    details = await client.async_get_device_details("s1", "ap")
    assert set(details.radios) == {"2.4", "6"}
    assert details.radios["2.4"].channel == 6
    assert details.radios["6"].channel is None
    assert details.radios["6"].channel_width_mhz == 320

    stats = await client.async_get_device_statistics("s1", "ap")
    assert stats.radio_tx_retries_pct == {"2.4": 12.5, "6": None}


PAGE = {"offset": 0, "limit": 200}
DEVICE = {
    "id": "d1",
    "name": "Gateway",
    "model": "UCG Ultra",
    "macAddress": "aa:bb:cc:00:00:01",
    "ipAddress": "192.168.1.1",
    "state": "ONLINE",
    "firmwareVersion": "4.1.13",
    "firmwareUpdatable": True,
    "features": ["gateway"],
    "interfaces": ["ports"],
    "supported": True,
}
CLIENT = {
    "id": "c1",
    "name": "Phone",
    "type": "WIRELESS",
    "macAddress": "11:22:33:44:55:66",
    "access": {"type": "DEFAULT"},
}
# Personal data of an invalid client; it must never appear in the log.
SECRET_CLIENT_NAME = "Annas iPhone"
SECRET_MAC = "de:ad:be:ef:00:01"


def _page(entries: list) -> dict:
    return {**PAGE, "data": entries, "count": len(entries), "totalCount": len(entries)}


def _assert_no_personal_data(text: str) -> None:
    for secret in (SECRET_CLIENT_NAME, SECRET_MAC, "192.168.1.1", "key"):
        assert secret not in text


async def test_invalid_devices_are_skipped(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Devices with missing or unexpected fields are skipped, the rest is kept."""
    without_name = {k: v for k, v in DEVICE.items() if k != "name"}
    aioclient_mock.get(
        f"{BASE}/v1/sites/s1/devices?offset=0&limit=200",
        json=_page(
            [
                {**without_name, "id": "d2", "macAddress": SECRET_MAC},
                DEVICE,
                {**DEVICE, "id": "d3", "firmwareUpdatable": "yes"},
                {**DEVICE, "id": "d4", "features": None},
                {**DEVICE, "id": "d5", "features": [1]},
                None,
                "d6",
            ]
        ),
    )
    client = _client(hass)

    skipped_ids: set[str] = set()
    with caplog.at_level(logging.WARNING):
        devices = await client.async_get_devices("s1", skipped_ids=skipped_ids)

    # A missing (null) list counts as empty, a list with wrong entries not.
    assert [device.id for device in devices] == ["d1", "d4"]
    # Skipped devices that still have an ID are reported, so they are not
    # mistaken for removed devices.
    assert skipped_ids == {"d2", "d3", "d5"}
    assert devices[1].features == frozenset()
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 4
    assert "/v1/sites/{siteId}/devices" in warnings[0]
    assert "device skipped: field 'name' is missing" in warnings[0]
    assert "field 'firmwareUpdatable' has an unexpected type" in warnings[1]
    assert "field 'features' has an unexpected type" in warnings[2]
    assert "device is not an object" in warnings[3]
    _assert_no_personal_data(caplog.text)


async def test_invalid_client_is_skipped_and_logged_once(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A client without a required field is skipped; the warning is not repeated."""
    aioclient_mock.get(
        f"{BASE}/v1/sites/s1/clients?offset=0&limit=200",
        json=_page(
            [
                {k: v for k, v in CLIENT.items() if k != "id"}
                | {"name": SECRET_CLIENT_NAME, "macAddress": SECRET_MAC},
                CLIENT,
                {**CLIENT, "id": "c2", "connectedAt": 1700000000},
            ]
        ),
    )
    client = _client(hass)

    with caplog.at_level(logging.DEBUG):
        assert [c.id for c in await client.async_get_clients("s1")] == ["c1"]
        assert [c.id for c in await client.async_get_clients("s1")] == ["c1"]

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert "client skipped: field 'id' is missing" in warnings[0]
    assert "client skipped: field 'connectedAt' has an unexpected type" in warnings[1]
    _assert_no_personal_data(caplog.text)


async def test_invalid_site_is_skipped(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A site without internal reference is skipped."""
    aioclient_mock.get(
        f"{BASE}/v1/sites?offset=0&limit=200",
        json=_page(
            [
                {"id": "s1", "name": "Default"},
                {"id": "s2", "name": "Office", "internalReference": "office"},
            ]
        ),
    )
    assert await _client(hass).async_get_sites() == [
        UnifiSite("s2", "Office", "office")
    ]


async def test_invalid_ports_and_radios_are_skipped(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Invalid ports and radios are skipped, the device details are kept."""
    port = {"idx": 1, "state": "UP", "connector": "RJ45", "maxSpeedMbps": 1000}
    poe = {"enabled": True, "state": "UP", "standard": "802.3at", "type": 2}
    radio = {"frequencyGHz": 5, "wlanStandard": "802.11ax", "channelWidthMHz": 80}
    aioclient_mock.get(
        f"{BASE}/v1/sites/s1/devices/d1",
        json={
            "id": "d1",
            "uplink": {"deviceId": "gw"},
            "interfaces": {
                "ports": [
                    port,
                    {**port, "idx": 2, "maxSpeedMbps": None},
                    {**port, "idx": 3, "poe": {**poe, "type": "four"}},
                    {**port, "idx": 4, "poe": {**poe, "enabled": None}},
                    {**port, "idx": 5, "poe": poe},
                    "port 6",
                ],
                "radios": [
                    radio,
                    {**radio, "frequencyGHz": "6"},
                    {k: v for k, v in radio.items() if k != "wlanStandard"},
                ],
            },
        },
    )
    aioclient_mock.get(
        f"{BASE}/v1/sites/s1/devices/d1/statistics/latest",
        json={
            "cpuUtilizationPct": 3,
            "interfaces": {
                "radios": [
                    {"frequencyGHz": 5, "txRetriesPct": 1.5},
                    {"txRetriesPct": 2.5},
                ]
            },
        },
    )
    client = _client(hass)

    with caplog.at_level(logging.WARNING):
        details = await client.async_get_device_details("s1", "d1")
        stats = await client.async_get_device_statistics("s1", "d1")

    assert set(details.ports) == {1, 5}
    assert details.ports[5].poe.type == 2
    assert set(details.radios) == {"5"}
    assert details.uplink_device_id == "gw"
    assert stats.cpu_utilization_pct == 3
    assert stats.radio_tx_retries_pct == {"5": 1.5}
    assert "port skipped: field 'maxSpeedMbps' is missing" in caplog.text
    assert "port skipped: unexpected value (ValueError)" in caplog.text
    assert "port skipped: field 'enabled' is missing" in caplog.text
    assert "port skipped: port is not an object" in caplog.text
    assert "radio skipped: field 'frequencyGHz' has an unexpected type" in caplog.text
    assert "radio skipped: field 'wlanStandard' is missing" in caplog.text
    assert "radio skipped: field 'frequencyGHz' is missing" in caplog.text
    assert "/v1/sites/{siteId}/devices/{deviceId}/statistics/latest" in caplog.text


@pytest.mark.parametrize(
    ("url", "kwargs", "call"),
    [
        # Invalid JSON, e.g. a cut-off body.
        ("/v1/info", {"text": '{"applicationVersion": '}, "info"),
        # A proxy answers with an HTML page instead of the API.
        ("/v1/info", {"text": "<html>Login</html>"}, "info"),
        ("/v1/info", {"json": {}}, "info"),
        ("/v1/info", {"json": ["10.3.58"]}, "info"),
        ("/v1/sites?offset=0&limit=200", {"json": {"data": []}}, "sites"),
        ("/v1/sites?offset=0&limit=200", {"json": []}, "sites"),
        ("/v1/sites/s1/devices/d1", {"json": []}, "details"),
        ("/v1/sites/s1/devices/d1", {"json": {"interfaces": []}}, "details"),
        ("/v1/sites/s1/devices/d1", {"json": {"uplink": "gw"}}, "details"),
        ("/v1/sites/s1/devices/d1/statistics/latest", {"text": "x"}, "statistics"),
        (
            "/v1/sites/s1/devices/d1/statistics/latest",
            {"json": {"uptimeSec": "1 day", "interfaces": {}}},
            "statistics",
        ),
    ],
)
async def test_unexpected_response(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    url: str,
    kwargs: dict,
    call: str,
) -> None:
    """Responses that cannot be read raise UnifiResponseError, not CannotConnect."""
    aioclient_mock.get(f"{BASE}{url}", **kwargs)
    client = _client(hass)
    calls = {
        "info": client.async_get_application_version,
        "sites": client.async_get_sites,
        "details": lambda: client.async_get_device_details("s1", "d1"),
        "statistics": lambda: client.async_get_device_statistics("s1", "d1"),
    }
    with pytest.raises(UnifiResponseError):
        await calls[call]()


async def test_content_type_error_is_response_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """aiohttp's ContentTypeError (a ClientError) is no connection problem.

    aiohttp raises it from ``response.json()`` for a non-JSON content type.
    """
    aioclient_mock.get(f"{BASE}/v1/info", text="<html>Login</html>")
    with (
        patch.object(
            AiohttpClientMockResponse,
            "json",
            side_effect=aiohttp.ContentTypeError(None, (), message="text/html"),
        ),
        pytest.raises(UnifiResponseError),
    ):
        await _client(hass).async_get_application_version()
