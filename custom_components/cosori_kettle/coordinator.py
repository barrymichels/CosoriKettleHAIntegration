"""Poll the kettle using Home Assistant's connectable Bluetooth devices."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import NoReturn

from bleak.backends.device import BLEDevice
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_HANDSHAKE, DOMAIN, UPDATE_INTERVAL
from .cosori_kettle_ble import CosoriKettleDevice
from .cosori_kettle_ble.exceptions import (
    CosoriKettleConnectionError,
    CosoriKettleError,
    CosoriKettleTimeoutError,
)

_LOGGER = logging.getLogger(__name__)


class CosoriKettleDataUpdateCoordinator(DataUpdateCoordinator[None]):
    """Own one persistent BLE connection and its polling lifecycle."""

    def __init__(
        self, hass: HomeAssistant, ble_device: BLEDevice, entry: ConfigEntry
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{ble_device.address}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.address = ble_device.address
        handshake = entry.data.get(CONF_HANDSHAKE)
        self.device = CosoriKettleDevice(
            device=ble_device,
            disconnect_callback=self._handle_disconnect,
            ble_device_callback=self._get_ble_device,
            handshake=(
                [bytes.fromhex(packet) for packet in handshake] if handshake else None
            ),
        )

    @callback
    def _get_ble_device(self) -> BLEDevice:
        """Resolve the current HA adapter/proxy instead of using a stale route."""
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise CosoriKettleConnectionError(f"Kettle {self.address} is not in range")
        return device

    @callback
    def _handle_disconnect(self, device: BLEDevice) -> None:
        if not self._shutdown_requested:
            self.async_set_update_error(UpdateFailed("Kettle disconnected"))

    async def _async_update_data(self) -> None:
        try:
            await self.device.update()
        except CosoriKettleError as err:
            raise UpdateFailed(str(err)) from err

    async def async_shutdown(self) -> None:
        """Cancel HA refresh work before releasing the BLE connection."""
        await super().async_shutdown()
        await self.device.disconnect()

    @property
    def current_temp_c(self) -> float | None:
        return self.device.current_temp_c

    @property
    def target_temp_c(self) -> float | None:
        return self.device.target_temp_c

    @property
    def on_base(self) -> bool | None:
        return self.device.on_base

    @property
    def heating(self) -> bool:
        return self.device.heating

    async def async_set_temperature(
        self, temperature: float, *, start: bool | None = None
    ) -> None:
        try:
            refreshed = await self.device.set_target_temperature(
                temperature, start=start
            )
        except CosoriKettleError as err:
            self._raise_command_error(err)
        if refreshed:
            self.async_set_updated_data(None)
        else:
            self.async_update_listeners()

    def _raise_command_error(self, err: CosoriKettleError) -> NoReturn:
        if isinstance(err, (CosoriKettleConnectionError, CosoriKettleTimeoutError)):
            self.async_set_update_error(UpdateFailed(str(err)))
            raise HomeAssistantError(str(err)) from err
        raise ServiceValidationError(str(err)) from err

    async def async_start_heating(self) -> None:
        try:
            await self.device.start_heating()
        except CosoriKettleError as err:
            self._raise_command_error(err)
        self.async_set_updated_data(None)

    async def async_stop_heating(self) -> None:
        try:
            await self.device.stop_heating()
        except CosoriKettleError as err:
            self._raise_command_error(err)
        self.async_set_updated_data(None)
