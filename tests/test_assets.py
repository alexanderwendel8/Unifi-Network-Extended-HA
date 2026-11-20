"""Consistency checks for icons, translations and brand images."""

import json
from pathlib import Path

from PIL import Image

from custom_components.unifi_network_extended.sensor import (
    DEVICE_SENSORS,
    DEVICE_STATES,
    SITE_SENSORS,
    STATISTICS_SENSORS,
    UPTIME_SENSOR,
)

COMPONENT = Path(__file__).parents[1] / "custom_components" / "unifi_network_extended"


def test_every_sensor_has_an_icon_and_a_name() -> None:
    """Each sensor translation key has an icon and a translated name."""
    icons = json.loads((COMPONENT / "icons.json").read_text())["entity"]["sensor"]
    strings = json.loads((COMPONENT / "strings.json").read_text())["entity"]["sensor"]
    keys = {
        description.translation_key
        for description in (
            *SITE_SENSORS,
            *DEVICE_SENSORS,
            *STATISTICS_SENSORS,
            UPTIME_SENSOR,
        )
    }
    assert keys == set(icons) == set(strings)
    for key in keys:
        assert icons[key]["default"].startswith("mdi:")


def test_device_state_icons_cover_all_states() -> None:
    """Every device state has its own icon."""
    icons = json.loads((COMPONENT / "icons.json").read_text())
    assert set(icons["entity"]["sensor"]["device_state"]["state"]) == set(DEVICE_STATES)


def test_brand_images() -> None:
    """Brand icons follow the Home Assistant brand image requirements."""
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        with Image.open(COMPONENT / "brand" / name) as image:
            assert image.format == "PNG"
            assert image.size == (size, size)
            assert image.mode == "RGBA"
            # Trimmed: the visible content reaches all edges.
            assert image.getbbox() == (0, 0, size, size)
