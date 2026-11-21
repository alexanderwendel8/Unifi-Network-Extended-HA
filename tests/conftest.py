"""Fixtures for UniFi Network Extended tests."""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_network_extended.api import (
    UnifiClient,
    UnifiDevice,
    UnifiDeviceDetails,
    UnifiDeviceStatistics,
    UnifiPort,
    UnifiPortPoe,
    UnifiSite,
)
from custom_components.unifi_network_extended.const import CONF_SITE_ID, DOMAIN

SITE = UnifiSite("site-default", "Default", "default")

GATEWAY = UnifiDevice(
    id="dev-gw",
    name="Gateway",
    model="UCG Ultra",
    mac_address="AA:BB:CC:00:00:01",
    ip_address="192.168.1.1",
    state="ONLINE",
    firmware_version="4.1.13",
    firmware_updatable=True,
    features=frozenset({"gateway", "switching"}),
    interfaces=frozenset({"ports"}),
)

# Gateway ports: 1 = PoE camera (up), 2 = PoE disabled, 3 = SFP+ without PoE.
GATEWAY_PORTS = {
    1: UnifiPort(
        idx=1,
        state="UP",
        connector="RJ45",
        max_speed_mbps=2500,
        speed_mbps=1000,
        poe=UnifiPortPoe(enabled=True, state="UP", standard="802.3at", type=2),
    ),
    2: UnifiPort(
        idx=2,
        state="DOWN",
        connector="RJ45",
        max_speed_mbps=2500,
        speed_mbps=None,
        poe=UnifiPortPoe(enabled=False, state="DOWN", standard="802.3at", type=2),
    ),
    3: UnifiPort(
        idx=3,
        state="UP",
        connector="SFPPLUS",
        max_speed_mbps=10000,
        speed_mbps=10000,
        poe=None,
    ),
}
ACCESS_POINT = UnifiDevice(
    id="dev-ap",
    name="Access Point",
    model="U7 Pro",
    mac_address="AA:BB:CC:00:00:02",
    ip_address="192.168.1.2",
    state="OFFLINE",
    firmware_version="8.0.0",
    firmware_updatable=False,
    features=frozenset({"accessPoint"}),
)

PHONE = UnifiClient(
    id="client-phone",
    name="Phone",
    type="WIRELESS",
    mac_address="11:22:33:44:55:66",
    ip_address="192.168.1.50",
    connected_at=datetime(2026, 11, 18, 8, 0, tzinfo=UTC),
    uplink_device_id="dev-ap",
    access_type="DEFAULT",
)
NAS = UnifiClient(
    id="client-nas",
    name="NAS",
    type="WIRED",
    mac_address="11:22:33:44:55:77",
    ip_address="192.168.1.10",
    connected_at=None,
    uplink_device_id="dev-gw",
    access_type="DEFAULT",
)
VPN_USER = UnifiClient(
    id="client-vpn",
    name="VPN user",
    type="VPN",
    mac_address=None,
    ip_address="10.0.0.2",
    connected_at=None,
    uplink_device_id=None,
    access_type="DEFAULT",
)

GATEWAY_STATS = UnifiDeviceStatistics(
    uptime_sec=3600,
    cpu_utilization_pct=12.5,
    memory_utilization_pct=40.0,
    load_average_1min=0.5,
    load_average_5min=0.4,
    load_average_15min=0.3,
    uplink_rx_rate_bps=50_000_000,
    uplink_tx_rate_bps=10_000_000,
)

# The gateway is connected to nothing (uplink None), the access point to it.
GATEWAY_DETAILS = UnifiDeviceDetails(
    ports=GATEWAY_PORTS,
    uplink_device_id=None,
    provisioned_at=datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
    adopted_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
)
ACCESS_POINT_DETAILS = UnifiDeviceDetails(
    ports={},
    uplink_device_id=GATEWAY.id,
    provisioned_at=None,
    adopted_at=None,
)


async def _device_details(site_id: str, device_id: str) -> UnifiDeviceDetails:
    return GATEWAY_DETAILS if device_id == GATEWAY.id else ACCESS_POINT_DETAILS


API = "custom_components.unifi_network_extended.api.UnifiApiClient"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a config entry added to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Default",
        unique_id=SITE.id,
        data={
            CONF_HOST: "192.168.1.1",
            CONF_PORT: 443,
            CONF_API_KEY: "secret-key",
            CONF_VERIFY_SSL: True,
            CONF_SITE_ID: SITE.id,
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_api() -> Generator[dict[str, AsyncMock]]:
    """Patch all API client methods with sample data."""
    with (
        patch(f"{API}.async_get_sites", return_value=[SITE]) as sites,
        patch(
            f"{API}.async_get_devices", return_value=[GATEWAY, ACCESS_POINT]
        ) as devices,
        patch(
            f"{API}.async_get_clients", return_value=[PHONE, NAS, VPN_USER]
        ) as clients,
        patch(
            f"{API}.async_get_device_statistics", return_value=GATEWAY_STATS
        ) as statistics,
        patch(f"{API}.async_restart_device", return_value=None) as restart,
        patch(
            f"{API}.async_get_device_details", side_effect=_device_details
        ) as details,
        patch(f"{API}.async_power_cycle_port", return_value=None) as power_cycle,
    ):
        yield {
            "sites": sites,
            "devices": devices,
            "clients": clients,
            "statistics": statistics,
            "restart": restart,
            "details": details,
            "power_cycle": power_cycle,
        }
