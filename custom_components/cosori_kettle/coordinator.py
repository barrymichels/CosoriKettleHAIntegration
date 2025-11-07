"""DataUpdateCoordinator for Cosori Kettle."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from bleak.backends.device import BLEDevice

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL
from .cosori_kettle_ble import CosoriKettleDevice
from .cosori_kettle_ble.exceptions import (
    CosoriKettleConnectionError,
    CosoriKettleError,
)

_LOGGER = logging.getLogger(__name__)


class CosoriKettleDataUpdateCoordinator(DataUpdateCoordinator[None]):
    """Class to manage fetching Cosori Kettle data."""

    def __init__(
        self,
        hass: HomeAssistant,
        ble_device: BLEDevice,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{ble_device.address}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.ble_device = ble_device
        self.entry = entry
        self.device = CosoriKettleDevice(
            device=ble_device,
            disconnect_callback=self._handle_disconnect,
        )
        self._connection_lost = False

    @callback
    def _handle_disconnect(self, device: BLEDevice) -> None:
        """Handle device disconnect."""
        _LOGGER.warning("Kettle %s disconnected", device.address)
        self._connection_lost = True

    async def _async_update_data(self) -> None:
        """Fetch data from the kettle."""
        try:
            # Ensure we're connected
            if not self.device.is_connected:
                _LOGGER.debug("Reconnecting to kettle")
                ble_device = bluetooth.async_ble_device_from_address(
                    self.hass, self.ble_device.address, connectable=True
                )
                if ble_device:
                    self.ble_device = ble_device
                    self.device._device = ble_device

            # Poll for status update
            await self.device.update()
            self._connection_lost = False

        except CosoriKettleConnectionError as err:
            if not self._connection_lost:
                _LOGGER.error("Connection error: %s", err)
            raise UpdateFailed(f"Connection error: {err}") from err
        except CosoriKettleError as err:
            _LOGGER.error("Communication error: %s", err)
            raise UpdateFailed(f"Communication error: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error updating kettle data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        await self.device.disconnect()

    @property
    def current_temp_c(self) -> float | None:
        """Get current temperature in Celsius."""
        return self.device.current_temp_c

    @property
    def target_temp_c(self) -> float | None:
        """Get target temperature in Celsius."""
        return self.device.target_temp_c

    @property
    def on_base(self) -> bool:
        """Get on-base status."""
        return self.device.on_base

    @property
    def heating(self) -> bool:
        """Get heating status."""
        return self.device.heating

    async def async_set_temperature(self, temperature: float) -> None:
        """Set target temperature."""
        await self.device.set_target_temperature(temperature)
        await self.async_request_refresh()

    async def async_start_heating(self) -> None:
        """Start heating."""
        await self.device.start_heating()
        await self.async_request_refresh()

    async def async_stop_heating(self) -> None:
        """Stop heating."""
        await self.device.stop_heating()
        await self.async_request_refresh()
