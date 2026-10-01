"""The Cosori Kettle integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import CosoriKettleDataUpdateCoordinator

CosoriKettleConfigEntry = ConfigEntry[CosoriKettleDataUpdateCoordinator]

PLATFORMS = [Platform.WATER_HEATER, Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: CosoriKettleConfigEntry
) -> bool:
    """Set up a registered kettle, requiring an actual status response."""
    address = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )
    if ble_device is None:
        raise ConfigEntryNotReady(f"Kettle {address} is not in Bluetooth range")
    coordinator = CosoriKettleDataUpdateCoordinator(hass, ble_device, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_shutdown()
        raise

    async def async_stop(event: Event) -> None:
        await coordinator.async_shutdown()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop)
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CosoriKettleConfigEntry
) -> bool:
    """Unload entities; coordinator cleanup also runs through entry callbacks."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown()
    return unload_ok
