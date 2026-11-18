"""Constants for the UniFi Network Extended integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "unifi_network_extended"

CONF_SITE_ID: Final = "site_id"

DEFAULT_PORT: Final = 443
DEFAULT_VERIFY_SSL: Final = True

CONF_STATISTICS_INTERVAL: Final = "statistics_interval"
CONF_TRACK_CLIENTS: Final = "track_clients"

# Polling intervals in seconds. The official API offers no push mechanism.
DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_STATISTICS_INTERVAL: Final = 60
DEFAULT_TRACK_CLIENTS: Final = True

# Limit parallel statistics requests (one request per device).
STATISTICS_PARALLEL_REQUESTS: Final = 4
