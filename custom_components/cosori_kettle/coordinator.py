"""Poll the kettle using Home Assistant's connectable Bluetooth devices."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import NoReturn, TypeVar

from bleak.backends.device import BLEDevice
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    COMMAND_TIMEOUT,
    CONF_HANDSHAKE,
    DOMAIN,
    POLL_CONNECT_TIMEOUT,
    POLL_TIMEOUT,
    UPDATE_INTERVAL,
)
from .cosori_kettle_ble import CosoriKettleDevice
from .cosori_kettle_ble.exceptions import (
    CosoriKettleConnectionError,
    CosoriKettleError,
    CosoriKettleTimeoutError,
    CosoriKettleUnconfirmedError,
)

_LOGGER = logging.getLogger(__name__)

_CommandT = TypeVar("_CommandT")


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
            async with asyncio.timeout(POLL_TIMEOUT):
                await self.device.update(POLL_CONNECT_TIMEOUT)
        except TimeoutError as err:
            raise UpdateFailed(
                f"Status transaction did not finish within {POLL_TIMEOUT}s"
            ) from err
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

    async def _async_command(
        self, name: str, run: Callable[[], Awaitable[_CommandT]]
    ) -> _CommandT:
        """Run one control transaction under a strict deadline."""
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT):
                return await run()
        except TimeoutError:
            self._raise_command_error(
                CosoriKettleUnconfirmedError(
                    f"{name} did not finish within {COMMAND_TIMEOUT}s, so its "
                    "outcome is unconfirmed"
                )
            )
        except CosoriKettleError as err:
            self._raise_command_error(err)

    async def async_set_temperature(
        self, temperature: float, *, start: bool | None = None
    ) -> None:
        refreshed = await self._async_command(
            "Set target temperature",
            lambda: self.device.set_target_temperature(temperature, start=start),
        )
        if refreshed:
            self.async_set_updated_data(None)
        else:
            self.async_update_listeners()

    def _raise_command_error(self, err: CosoriKettleError) -> NoReturn:
        if isinstance(
            err,
            CosoriKettleConnectionError
            | CosoriKettleTimeoutError
            | CosoriKettleUnconfirmedError,
        ):
            self.async_set_update_error(UpdateFailed(str(err)))
            raise HomeAssistantError(str(err)) from err
        raise ServiceValidationError(str(err)) from err

    async def async_start_heating(self) -> None:
        await self._async_command("Start heating", self.device.start_heating)
        self.async_set_updated_data(None)

    async def async_stop_heating(self) -> None:
        await self._async_command("Stop heating", self.device.stop_heating)
        self.async_set_updated_data(None)
