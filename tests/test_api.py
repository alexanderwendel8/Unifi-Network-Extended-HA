"""Tests for the official UniFi Network API client."""

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.unifi_network_extended.api import (
    UnifiApiClient,
    UnifiApiError,
    UnifiCannotConnect,
    UnifiInvalidAuth,
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
