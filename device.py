"""Device registry info shared by the FranklinWH sensor and switch platforms."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

DOMAIN = "franklin_wh"


def gateway_device_info(serial: str, name: str) -> DeviceInfo:
    """One device per aGate, keyed by its serial number."""
    return DeviceInfo(
        identifiers={(DOMAIN, serial)},
        name=name,
        manufacturer="FranklinWH",
        model="aGate",
        serial_number=serial,
    )
