"""The Cosori Kettle integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import CosoriKettleDataUpdateCoordinator

CosoriKettleConfigEntry = ConfigEntry[CosoriKettleDataUpdateCoordinator]

PLATFORMS = [Platform.WATER_HEATER, Platform.SENSOR, Platform.BINARY_SENSOR]


def kettle_device_info(entry: CosoriKettleConfigEntry, address: str) -> DeviceInfo:
    """Build the device registry entry shared by every platform."""
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "connections": {(CONNECTION_BLUETOOTH, address)},
        "name": entry.title,
        "manufacturer": MANUFACTURER,
        "model": MODEL,
    }


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
        # Release the single kettle connection before HA retries setup.
        await coordinator.async_shutdown()
        raise

    async def async_stop(event: Event) -> None:
        await coordinator.async_shutdown()

    # HA stops entries with ConfigEntry.async_shutdown(), which does not run
    # unload callbacks, so releasing BLE on shutdown needs its own listener.
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop)
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CosoriKettleConfigEntry
) -> bool:
    """Unload entities; the coordinator releases BLE via its unload callback."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
