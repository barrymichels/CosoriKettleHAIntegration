"""The Cosori Kettle integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import CosoriKettleDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.WATER_HEATER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Cosori Kettle from a config entry."""
    address: str = entry.data[CONF_ADDRESS]

    # Get BLE device
    ble_device = bluetooth.async_ble_device_from_address(
        hass, address.upper(), connectable=True
    )

    if not ble_device:
        raise ConfigEntryNotReady(
            f"Could not find Cosori Kettle with address {address}. "
            "Try power cycling the device and ensure Bluetooth is enabled."
        )

    # Create coordinator
    coordinator = CosoriKettleDataUpdateCoordinator(hass, ble_device, entry)

    # Store coordinator in runtime_data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Start coordinator
    await coordinator.async_config_entry_first_refresh()

    # Forward to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: CosoriKettleDataUpdateCoordinator = hass.data[DOMAIN].pop(
            entry.entry_id
        )
        await coordinator.async_shutdown()

    return unload_ok
