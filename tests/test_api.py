"""Tests for the official UniFi Network API client."""

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
