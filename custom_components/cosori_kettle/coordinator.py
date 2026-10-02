"""Poll the kettle using Home Assistant's connectable Bluetooth devices."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, NoReturn, TypeVar

from bleak.backends.device import BLEDevice
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryError,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    COMMAND_TIMEOUT,
    CONF_HANDSHAKE,
    DOMAIN,
    POLL_CONNECT_TIMEOUT,
    POLL_TIMEOUT,
    UPDATE_INTERVAL,
)
from .cosori_kettle_ble import CosoriKettleDevice, parse_registration_handshake
from .cosori_kettle_ble.exceptions import (
    CosoriKettleConnectionError,
    CosoriKettleError,
    CosoriKettleTimeoutError,
    CosoriKettleUnconfirmedError,
)

_LOGGER = logging.getLogger(__name__)

_CommandT = TypeVar("_CommandT")


def _decode_handshake(entry: ConfigEntry) -> list[bytes] | None:
    """Decode the stored handshake, refusing frames that could heat."""
    stored = entry.data.get(CONF_HANDSHAKE)
    if not stored:
        return None
    # The parser reports every unusable shape as ValueError, so a corrupted or
    # hand-edited entry cannot escape as TypeError or AttributeError.
    try:
        return parse_registration_handshake(stored)
    except ValueError as err:
        raise ConfigEntryError(
            f"Stored handshake for {DOMAIN} is invalid: {err}"
        ) from err


class CosoriKettleDataUpdateCoordinator(DataUpdateCoordinator[None]):
    """Own one persistent BLE connection and its polling lifecycle."""

    def __init__(
        self, hass: HomeAssistant, ble_device: BLEDevice, entry: ConfigEntry
    ) -> None:
        # Decode before super().__init__() registers the shutdown callback: a bad
        # stored handshake must fail before a half-built coordinator exists.
        handshake = _decode_handshake(entry)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{ble_device.address}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.address = ble_device.address
        self.device = CosoriKettleDevice(
            device=ble_device,
            disconnect_callback=self._handle_disconnect,
            ble_device_callback=self._get_ble_device,
            handshake=handshake,
        )
        self._consecutive_failures = 0
        self._command_tasks: set[asyncio.Task[Any]] = set()
        self._poll_tasks: set[asyncio.Task[None]] = set()

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
        # The poll runs as a child task so shutdown can cancel a connection
        # attempt wedged in start_notify without cancelling the task that
        # hosts the refresh; connect() holds the connection lock throughout.
        poll = asyncio.ensure_future(
            self.device.update(POLL_CONNECT_TIMEOUT, POLL_TIMEOUT)
        )
        self._poll_tasks.add(poll)
        poll.add_done_callback(self._poll_tasks.discard)
        try:
            await asyncio.shield(poll)
        except asyncio.CancelledError:
            poll.cancel()
            await asyncio.gather(poll, return_exceptions=True)
            raise
        except TimeoutError as err:
            raise self._update_failed(
                f"Status transaction did not finish within {POLL_TIMEOUT}s"
            ) from err
        except CosoriKettleError as err:
            raise self._update_failed(str(err)) from err
        self._consecutive_failures = 0

    def _update_failed(self, message: str) -> UpdateFailed:
        """Back off after repeated failures so an absent kettle is not
        retried every few seconds forever."""
        self._consecutive_failures += 1
        err = UpdateFailed(message)
        err.retry_after = min(60, 2 * self._consecutive_failures)
        return err

    async def async_shutdown(self) -> None:
        """Cancel in-flight HA work before releasing the BLE connection."""
        await super().async_shutdown()
        # Production COMMAND_TIMEOUT (30 s) and POLL_TIMEOUT (15 s) exceed
        # HA's ~10 s wait for unload tasks, and a poll reconnecting inside
        # connect() holds the device's connection lock, so in-flight polls
        # and commands are cancelled rather than awaited.
        pending = self._command_tasks | self._poll_tasks
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await self.device.disconnect()

    @property
    def current_temp_c(self) -> float | None:
        return self.device.current_temp_c

    @property
    def reported_target_c(self) -> float | None:
        return self.device.reported_target_c

    @property
    def requested_target_c(self) -> float | None:
        return self.device.requested_target_c

    @property
    def pending_target_c(self) -> float | None:
        return self.device.pending_target_c

    @property
    def on_base(self) -> bool | None:
        return self.device.on_base

    @property
    def heating(self) -> bool:
        return self.device.heating

    async def _async_command(
        self, name: str, run: Callable[[], Awaitable[_CommandT]]
    ) -> _CommandT:
        """Run one control transaction under a strict deadline.

        The transaction runs as a child task so shutdown can cancel it
        without touching the host task: production COMMAND_TIMEOUT (30 s)
        exceeds Home Assistant's ~10 s wait for unload tasks.
        """
        command = asyncio.ensure_future(run())
        self._command_tasks.add(command)
        command.add_done_callback(self._command_tasks.discard)
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT):
                return await asyncio.shield(command)
        except asyncio.CancelledError:
            command.cancel()
            await asyncio.gather(command, return_exceptions=True)
            raise
        except TimeoutError:
            command.cancel()
            await asyncio.gather(command, return_exceptions=True)
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
