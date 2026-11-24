"""Sensors for UniFi Network Extended."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfFrequency,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import UnifiNetworkExtendedConfigEntry
from .api import (
    UnifiDevice,
    UnifiDeviceDetails,
    UnifiDeviceStatistics,
    UnifiPort,
    UnifiRadio,
)
from .coordinator import UnifiSiteData
from .entity import (
    UnifiApplicationInfoEntity,
    UnifiDeviceDetailsEntity,
    UnifiDeviceEntity,
    UnifiDeviceStatisticsEntity,
    UnifiPortEntity,
    UnifiPortEntityDescription,
    UnifiRadioEntity,
    UnifiRadioStatisticsEntity,
    UnifiSiteEntity,
    async_setup_port_entities,
    async_setup_radio_entities,
)

PARALLEL_UPDATES = 0  # Coordinator based, no per-entity polling.

# Device states from the "Adopted device overview" schema.
DEVICE_STATES = [
    "online",
    "offline",
    "pending_adoption",
    "updating",
    "getting_ready",
    "adopting",
    "deleting",
    "connection_interrupted",
    "isolated",
    "u5g_incorrect_topology",
]


@dataclass(frozen=True, kw_only=True)
class UnifiSiteSensorDescription(SensorEntityDescription):
    """Describes a sensor of the site."""

    value_fn: Callable[[UnifiSiteData], int]


@dataclass(frozen=True, kw_only=True)
class UnifiDeviceSensorDescription(SensorEntityDescription):
    """Describes a sensor based on the device overview."""

    value_fn: Callable[[UnifiDevice], str | None]


@dataclass(frozen=True, kw_only=True)
class UnifiStatisticsSensorDescription(SensorEntityDescription):
    """Describes a sensor based on the latest device statistics."""

    value_fn: Callable[[UnifiDeviceStatistics], float | int | None]


NETWORK_VERSION_SENSOR = SensorEntityDescription(
    key="network_version",
    translation_key="network_version",
    entity_category=EntityCategory.DIAGNOSTIC,
)


def _count_clients(client_type: str) -> Callable[[UnifiSiteData], int]:
    return lambda data: sum(
        client.type == client_type for client in data.clients.values()
    )


SITE_SENSORS: tuple[UnifiSiteSensorDescription, ...] = (
    UnifiSiteSensorDescription(
        key="clients",
        translation_key="clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.clients),
    ),
    UnifiSiteSensorDescription(
        key="clients_wired",
        translation_key="clients_wired",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_count_clients("WIRED"),
    ),
    UnifiSiteSensorDescription(
        key="clients_wireless",
        translation_key="clients_wireless",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_count_clients("WIRELESS"),
    ),
    UnifiSiteSensorDescription(
        key="clients_vpn",
        translation_key="clients_vpn",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda data: sum(
            client.type in ("VPN", "TELEPORT") for client in data.clients.values()
        ),
    ),
    UnifiSiteSensorDescription(
        key="clients_guest",
        translation_key="clients_guest",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda data: sum(
            client.access_type == "GUEST" for client in data.clients.values()
        ),
    ),
    UnifiSiteSensorDescription(
        key="devices",
        translation_key="devices",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.devices),
    ),
)

DEVICE_SENSORS: tuple[UnifiDeviceSensorDescription, ...] = (
    UnifiDeviceSensorDescription(
        key="state",
        translation_key="device_state",
        device_class=SensorDeviceClass.ENUM,
        options=DEVICE_STATES,
        value_fn=lambda device: (
            state if (state := device.state.lower()) in DEVICE_STATES else None
        ),
    ),
    UnifiDeviceSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.ip_address or None,
    ),
    UnifiDeviceSensorDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda device: device.firmware_version or None,
    ),
)

STATISTICS_SENSORS: tuple[UnifiStatisticsSensorDescription, ...] = (
    UnifiStatisticsSensorDescription(
        key="cpu_utilization",
        translation_key="cpu_utilization",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda stats: stats.cpu_utilization_pct,
    ),
    UnifiStatisticsSensorDescription(
        key="memory_utilization",
        translation_key="memory_utilization",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda stats: stats.memory_utilization_pct,
    ),
    UnifiStatisticsSensorDescription(
        key="uplink_rx_rate",
        translation_key="uplink_rx_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BITS_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: stats.uplink_rx_rate_bps,
    ),
    UnifiStatisticsSensorDescription(
        key="uplink_tx_rate",
        translation_key="uplink_tx_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BITS_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: stats.uplink_tx_rate_bps,
    ),
    UnifiStatisticsSensorDescription(
        key="load_average_1min",
        translation_key="load_average_1min",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda stats: stats.load_average_1min,
    ),
    UnifiStatisticsSensorDescription(
        key="load_average_5min",
        translation_key="load_average_5min",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda stats: stats.load_average_5min,
    ),
    UnifiStatisticsSensorDescription(
        key="load_average_15min",
        translation_key="load_average_15min",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda stats: stats.load_average_15min,
    ),
)

# Enum values from the "Port overview" / "Port PoE overview" schemas.
PORT_CONNECTORS = ["rj45", "sfp", "sfpplus", "sfp28", "qsfp28"]
PORT_POE_STATES = ["up", "down", "limited", "unknown"]


def _enum(value: str, options: list[str]) -> str | None:
    return value if (value := value.lower()) in options else None


@dataclass(frozen=True, kw_only=True)
class UnifiPortSensorDescription(UnifiPortEntityDescription, SensorEntityDescription):
    """Describes a sensor of a device port."""

    value_fn: Callable[[UnifiPort], str | int | None]


def _has_poe(port: UnifiPort) -> bool:
    return port.poe is not None


PORT_SENSORS: tuple[UnifiPortSensorDescription, ...] = (
    UnifiPortSensorDescription(
        key="link_speed",
        translation_key="port_link_speed",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        # Only reported while the link is up.
        value_fn=lambda port: port.speed_mbps if port.state == "UP" else 0,
    ),
    UnifiPortSensorDescription(
        key="max_speed",
        translation_key="port_max_speed",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda port: port.max_speed_mbps,
    ),
    UnifiPortSensorDescription(
        key="connector",
        translation_key="port_connector",
        device_class=SensorDeviceClass.ENUM,
        options=PORT_CONNECTORS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda port: _enum(port.connector, PORT_CONNECTORS),
    ),
    UnifiPortSensorDescription(
        key="poe_state",
        translation_key="port_poe_state",
        device_class=SensorDeviceClass.ENUM,
        options=PORT_POE_STATES,
        exists_fn=_has_poe,
        # Only enabled by default where PoE is switched on.
        enabled_fn=lambda port: port.poe is not None and port.poe.enabled,
        value_fn=lambda port: (
            _enum(port.poe.state, PORT_POE_STATES) if port.poe else None
        ),
    ),
    UnifiPortSensorDescription(
        key="poe_standard",
        translation_key="port_poe_standard",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        exists_fn=_has_poe,
        value_fn=lambda port: port.poe.standard if port.poe else None,
    ),
    UnifiPortSensorDescription(
        key="poe_type",
        translation_key="port_poe_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        exists_fn=_has_poe,
        value_fn=lambda port: port.poe.type if port.poe else None,
    ),
)

DEVICE_CLIENTS_SENSOR = SensorEntityDescription(
    key="clients",
    translation_key="device_clients",
    state_class=SensorStateClass.MEASUREMENT,
)


@dataclass(frozen=True, kw_only=True)
class UnifiDetailsSensorDescription(SensorEntityDescription):
    """Describes a sensor based on the device details."""

    value_fn: Callable[[UnifiDeviceDetails, UnifiSiteData], str | datetime | None]


def _uplink_device_name(details: UnifiDeviceDetails, data: UnifiSiteData) -> str | None:
    """Name of the device this device is connected to (None for the gateway)."""
    if details.uplink_device_id is None:
        return None
    if (uplink := data.devices.get(details.uplink_device_id)) is None:
        return None
    return uplink.name


DETAILS_SENSORS: tuple[UnifiDetailsSensorDescription, ...] = (
    UnifiDetailsSensorDescription(
        key="uplink_device",
        translation_key="uplink_device",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_uplink_device_name,
    ),
    UnifiDetailsSensorDescription(
        key="last_provisioned",
        translation_key="last_provisioned",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda details, data: details.provisioned_at,
    ),
)


@dataclass(frozen=True, kw_only=True)
class UnifiRadioSensorDescription(SensorEntityDescription):
    """Describes a sensor of an access point radio."""

    value_fn: Callable[[UnifiRadio], str | int | None]
    # Whether the radio provides the value at all (older API versions).
    exists_fn: Callable[[UnifiRadio], bool] = lambda radio: True


RADIO_TX_POWER_MODES = ["auto", "low", "medium", "high", "custom", "disabled"]

RADIO_SENSORS: tuple[UnifiRadioSensorDescription, ...] = (
    UnifiRadioSensorDescription(
        key="channel",
        translation_key="radio_channel",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda radio: radio.channel,
    ),
    UnifiRadioSensorDescription(
        key="channel_width",
        translation_key="radio_channel_width",
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda radio: radio.channel_width_mhz,
    ),
    UnifiRadioSensorDescription(
        key="wlan_standard",
        translation_key="radio_wlan_standard",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda radio: radio.wlan_standard,
    ),
    UnifiRadioSensorDescription(
        key="tx_power_mode",
        translation_key="radio_tx_power_mode",
        device_class=SensorDeviceClass.ENUM,
        options=RADIO_TX_POWER_MODES,
        entity_category=EntityCategory.DIAGNOSTIC,
        # txPowerMode exists since UniFi Network API 11.0.
        exists_fn=lambda radio: radio.tx_power_mode is not None,
        value_fn=lambda radio: (
            _enum(radio.tx_power_mode, RADIO_TX_POWER_MODES)
            if radio.tx_power_mode
            else None
        ),
    ),
)

RADIO_TX_RETRIES_SENSOR = SensorEntityDescription(
    key="tx_retries",
    translation_key="radio_tx_retries",
    native_unit_of_measurement=PERCENTAGE,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=1,
)

UPTIME_SENSOR = SensorEntityDescription(
    key="uptime",
    translation_key="uptime",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnifiNetworkExtendedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    site_coordinator = entry.runtime_data.site_coordinator
    statistics_coordinator = entry.runtime_data.statistics_coordinator
    details_coordinator = entry.runtime_data.details_coordinator

    async_add_entities(
        UnifiSiteSensor(site_coordinator, description) for description in SITE_SENSORS
    )
    async_add_entities(
        [
            UnifiNetworkVersionSensor(
                entry.runtime_data.application_info_coordinator,
                site_coordinator.site,
                NETWORK_VERSION_SENSOR,
            )
        ]
    )

    known: set[str] = set()

    @callback
    def _async_add_new_devices() -> None:
        # Forget removed devices, so they get new entities if they come back.
        known.intersection_update(site_coordinator.data.devices)
        new_ids = set(site_coordinator.data.devices) - known
        if not new_ids:
            return
        known.update(new_ids)
        entities: list[SensorEntity] = []
        for device_id in new_ids:
            entities.extend(
                UnifiDeviceSensor(site_coordinator, description, device_id)
                for description in DEVICE_SENSORS
            )
            entities.extend(
                UnifiStatisticsSensor(
                    statistics_coordinator, site_coordinator, description, device_id
                )
                for description in STATISTICS_SENSORS
            )
            entities.append(
                UnifiUptimeSensor(
                    statistics_coordinator, site_coordinator, UPTIME_SENSOR, device_id
                )
            )
            entities.append(
                UnifiDeviceClientsSensor(
                    site_coordinator, DEVICE_CLIENTS_SENSOR, device_id
                )
            )
            entities.extend(
                UnifiDetailsSensor(details_coordinator, description, device_id)
                for description in DETAILS_SENSORS
            )
        async_add_entities(entities)

    _async_add_new_devices()
    entry.async_on_unload(site_coordinator.async_add_listener(_async_add_new_devices))

    async_setup_radio_entities(
        entry,
        details_coordinator,
        lambda details: details.radios,
        lambda device_id, band: (
            UnifiRadioSensor(details_coordinator, description, device_id, band)
            for description in RADIO_SENSORS
            if description.exists_fn(details_coordinator.data[device_id].radios[band])
        ),
        async_add_entities,
    )
    async_setup_radio_entities(
        entry,
        statistics_coordinator,
        lambda statistics: statistics.radio_tx_retries_pct,
        lambda device_id, band: (
            UnifiRadioTxRetriesSensor(
                statistics_coordinator, RADIO_TX_RETRIES_SENSOR, device_id, band
            ),
        ),
        async_add_entities,
    )

    async_setup_port_entities(
        entry,
        details_coordinator,
        PORT_SENSORS,
        UnifiPortSensor,
        async_add_entities,
    )


class UnifiSiteSensor(UnifiSiteEntity, SensorEntity):
    """Sensor of the site, e.g. number of connected clients."""

    entity_description: UnifiSiteSensorDescription

    @property
    def native_value(self) -> int:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)


class UnifiNetworkVersionSensor(UnifiApplicationInfoEntity, SensorEntity):
    """Version of the UniFi Network application, attached to the site device."""

    @property
    def native_value(self) -> str | None:
        """Return the application version."""
        return self.coordinator.data


class UnifiDeviceSensor(UnifiDeviceEntity, SensorEntity):
    """Sensor based on the device overview."""

    entity_description: UnifiDeviceSensorDescription

    @property
    def native_value(self) -> str | None:
        """Return the sensor value."""
        if (device := self.device) is None:
            return None
        return self.entity_description.value_fn(device)


class UnifiStatisticsSensor(UnifiDeviceStatisticsEntity, SensorEntity):
    """Sensor based on the latest device statistics."""

    entity_description: UnifiStatisticsSensorDescription

    @property
    def native_value(self) -> float | int | None:
        """Return the sensor value."""
        if (stats := self.statistics) is None:
            return None
        return self.entity_description.value_fn(stats)


# A new boot time is only accepted when it differs by more than this. Smaller
# differences come from rounding and from uptime and heartbeat not always being
# reported at exactly the same moment.
BOOT_TIME_TOLERANCE = timedelta(minutes=2)


class UnifiUptimeSensor(UnifiDeviceStatisticsEntity, RestoreSensor):
    """Time of the last device start, derived from the uptime.

    The value is restored after a restart or reload of Home Assistant and only
    changes on a real reboot of the device, so automations can trigger on it.
    """

    _last_boot: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last known boot time."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None and isinstance(
            last.native_value, datetime
        ):
            self._last_boot = last.native_value

    @property
    def native_value(self) -> datetime | None:
        """Return the boot time.

        The uptime refers to the last heartbeat of the device, so
        ``lastHeartbeatAt - uptimeSec`` gives the boot time independent of when
        Home Assistant polls; without a heartbeat ``now - uptime`` is used.
        """
        stats = self.statistics
        if stats is None or stats.uptime_sec is None:
            return self._last_boot
        reference = stats.last_heartbeat_at or dt_util.utcnow()
        boot = (reference - timedelta(seconds=stats.uptime_sec)).replace(microsecond=0)
        if self._last_boot is None or abs(boot - self._last_boot) > BOOT_TIME_TOLERANCE:
            self._last_boot = boot
        return self._last_boot


class UnifiPortSensor(UnifiPortEntity, SensorEntity):
    """Sensor of a device port."""

    entity_description: UnifiPortSensorDescription

    @property
    def native_value(self) -> str | int | None:
        """Return the sensor value."""
        if (port := self.port) is None:
            return None
        return self.entity_description.value_fn(port)


class UnifiDeviceClientsSensor(UnifiDeviceEntity, SensorEntity):
    """Number of clients connected directly to a device (``uplinkDeviceId``).

    Wireless clients count for their access point, wired clients for their
    switch or gateway.
    """

    @property
    def native_value(self) -> int:
        """Return the number of connected clients."""
        return sum(
            client.uplink_device_id == self.device_id
            for client in self.coordinator.data.clients.values()
        )


class UnifiDetailsSensor(UnifiDeviceDetailsEntity, SensorEntity):
    """Sensor based on the device details."""

    entity_description: UnifiDetailsSensorDescription

    @property
    def native_value(self) -> str | datetime | None:
        """Return the sensor value."""
        if (details := self.details) is None:
            return None
        return self.entity_description.value_fn(
            details, self.coordinator.site_coordinator.data
        )


class UnifiRadioSensor(UnifiRadioEntity, SensorEntity):
    """Sensor of an access point radio (channel, width, standard, TX power)."""

    entity_description: UnifiRadioSensorDescription

    @property
    def native_value(self) -> str | int | None:
        """Return the sensor value."""
        if (radio := self.radio) is None:
            return None
        return self.entity_description.value_fn(radio)


class UnifiRadioTxRetriesSensor(UnifiRadioStatisticsEntity, SensorEntity):
    """Share of retransmitted frames of a radio, a sign of interference."""

    @property
    def native_value(self) -> float | None:
        """Return the TX retries in percent."""
        if (statistics := self.coordinator.data.get(self.device_id)) is None:
            return None
        return statistics.radio_tx_retries_pct.get(self.band)
