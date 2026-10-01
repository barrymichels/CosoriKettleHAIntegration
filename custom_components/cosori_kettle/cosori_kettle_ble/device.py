"""Persistent Cosori BLE connection and serialized command transactions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from types import TracebackType

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import MAX_TEMP_C, MIN_TEMP_C, RX_CHAR_UUID, TX_CHAR_UUID
from .exceptions import (
    CosoriKettleConnectionError,
    CosoriKettleError,
    CosoriKettleTimeoutError,
)
from .protocol import (
    CosoriProtocol,
    KettleStatus,
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
)

_LOGGER = logging.getLogger(__name__)
STATUS_TIMEOUT = 5.0


class CosoriKettleDevice:
    """Use BLE devices supplied by HA so local adapters and proxies both work."""

    def __init__(
        self,
        device: BLEDevice,
        disconnect_callback: Callable[[BLEDevice], None] | None = None,
        ble_device_callback: Callable[[], BLEDevice] | None = None,
        handshake: list[bytes] | None = None,
    ) -> None:
        self._device = device
        self._ble_device_callback = ble_device_callback
        self._handshake = handshake
        self._client: BleakClient | None = None
        self._protocol = CosoriProtocol()
        self._disconnect_callback = disconnect_callback
        self._status: KettleStatus | None = None
        self._target_temp_f: int | None = None
        self._ready = False
        self._notifications_received = 0
        self._notification_event = asyncio.Event()
        self._connection_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()

    @property
    def address(self) -> str:
        """Return the device address."""
        return self._device.address

    @property
    def name(self) -> str:
        """Return the device name."""
        return self._device.name or "Cosori Kettle"

    @property
    def is_connected(self) -> bool:
        """A connected client is usable only after registration completes."""
        return self._ready and self._client is not None and self._client.is_connected

    @property
    def current_temp_f(self) -> float | None:
        return self._status.current_temp_f if self._status is not None else None

    @property
    def current_temp_c(self) -> float | None:
        temp = self.current_temp_f
        return fahrenheit_to_celsius(temp) if temp is not None else None

    @property
    def target_temp_f(self) -> float | None:
        return self._target_temp_f

    @property
    def target_temp_c(self) -> float | None:
        temp = self.target_temp_f
        return fahrenheit_to_celsius(temp) if temp is not None else None

    @property
    def on_base(self) -> bool | None:
        return self._status.on_base if self._status is not None else None

    @property
    def heating(self) -> bool:
        return self._status.heating if self._status is not None else False

    def _handle_disconnect(self, client: BleakClient) -> None:
        if client is not self._client:
            return
        self._ready = False
        self._status = None
        self._notification_event.set()
        if self._disconnect_callback:
            self._disconnect_callback(self._device)

    def _handle_notification(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        self._notifications_received += 1
        statuses = self._protocol.feed(data)
        _LOGGER.debug(
            "Kettle %s: received %d notification bytes, decoded %d status frames",
            self.address,
            len(data),
            len(statuses),
        )
        for status in statuses:
            self._status = status
            _LOGGER.debug(
                "Kettle %s: temperature=%s°F, setpoint=%s°F, on_base=%s, heating=%s",
                self.address,
                status.current_temp_f,
                status.target_temp_f,
                status.on_base,
                status.heating,
            )
            if self._target_temp_f is None and 104 <= status.target_temp_f <= 212:
                self._target_temp_f = int(status.target_temp_f)
            self._notification_event.set()

    async def connect(self, timeout: float = 30.0) -> None:
        """Connect with retries and register before allowing other operations."""
        async with self._connection_lock:
            if self.is_connected:
                return
            await self._disconnect()
            self._protocol = CosoriProtocol()
            self._notification_event.clear()
            try:
                if self._ble_device_callback:
                    self._device = self._ble_device_callback()
                _LOGGER.debug("Connecting to kettle %s", self.address)
                self._client = await establish_connection(
                    BleakClientWithServiceCache,
                    self._device,
                    self.name,
                    disconnected_callback=self._handle_disconnect,
                    ble_device_callback=self._ble_device_callback,
                    timeout=timeout,
                )
                _LOGGER.debug(
                    "Connected to kettle %s; subscribing to status", self.address
                )
                await self._client.start_notify(
                    str(RX_CHAR_UUID), self._handle_notification
                )
                for packet in self._handshake or self._protocol.build_hello_min():
                    await self._send_command(packet)
                    await asyncio.sleep(0.08)
                self._ready = True
                _LOGGER.debug("Kettle %s: registration sent", self.address)
            except BaseException as err:
                # Cancelled setup must release the proxy slot too.
                await self._disconnect()
                if isinstance(err, TimeoutError):
                    raise CosoriKettleTimeoutError(
                        "Timeout connecting to kettle"
                    ) from err
                if isinstance(err, (BleakError, OSError)):
                    raise CosoriKettleConnectionError(
                        f"Could not connect: {err}"
                    ) from err
                raise

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        self._ready = False
        self._status = None
        self._notification_event.set()
        if client is not None:
            try:
                # disconnect also removes notifications; a failed stop_notify
                # must never prevent releasing the BLE connection.
                await client.disconnect()
            except (BleakError, OSError, TimeoutError):
                _LOGGER.debug("Failed to disconnect %s", self.address, exc_info=True)

    async def disconnect(self) -> None:
        """Wait for active transactions, then release the connection."""
        async with self._operation_lock, self._connection_lock:
            await self._disconnect()

    async def _send_command(self, data: bytes) -> None:
        if self._client is None or not self._client.is_connected:
            raise CosoriKettleConnectionError("Kettle disconnected")
        try:
            await self._client.write_gatt_char(str(TX_CHAR_UUID), data, response=False)
        except (BleakError, OSError, TimeoutError) as err:
            await self._disconnect()
            raise CosoriKettleConnectionError(
                f"Could not write command: {err}"
            ) from err

    async def _wait_status(self, timeout: float = STATUS_TIMEOUT) -> None:
        try:
            await asyncio.wait_for(self._notification_event.wait(), timeout)
        except TimeoutError as err:
            await self._disconnect()
            raise CosoriKettleTimeoutError(
                f"No valid kettle status received from {self.address} "
                f"({self._notifications_received} BLE notifications "
                "received during poll)"
            ) from err
        if not self.is_connected or self._status is None:
            raise CosoriKettleConnectionError(
                "Kettle disconnected while awaiting status"
            )

    async def _poll(self) -> None:
        _LOGGER.debug("Kettle %s: requesting fresh status", self.address)
        self._notifications_received = 0
        self._notification_event.clear()
        await self._send_command(self._protocol.build_poll())
        await self._wait_status()

    async def update(self) -> None:
        """Poll and require a fresh valid status; never accept stale data."""
        async with self._operation_lock:
            await self.connect()
            await self._poll()

    async def set_target_temperature(
        self, temp_c: float, *, start: bool | None = None
    ) -> bool:
        """Stage/apply a target and return whether fresh status was received."""
        if not MIN_TEMP_C <= temp_c <= MAX_TEMP_C:
            raise CosoriKettleError(f"Temperature must be {MIN_TEMP_C}-{MAX_TEMP_C}°C")
        async with self._operation_lock:
            self._target_temp_f = round(celsius_to_fahrenheit(temp_c))
            if start is False:
                await self.connect()
                await self._stop_heating()
                return True
            elif start is True or self.heating:
                await self.connect()
                await self._start_heating()
                return True
            return False

    async def _start_heating(self) -> None:
        if self._status is None:
            await self._poll()
        if self.on_base is not True:
            raise CosoriKettleError("Place the kettle on its base before heating")
        if self._target_temp_f is None:
            raise CosoriKettleError("Set a target temperature before heating")
        await self._send_command(self._protocol.build_hello5())
        await asyncio.sleep(0.06)
        self._notification_event.clear()
        await self._send_command(self._protocol.build_setpoint(self._target_temp_f))
        await asyncio.sleep(0.1)
        # The working implementation permits control after a 2s status wait.
        try:
            await asyncio.wait_for(self._notification_event.wait(), 2.0)
        except TimeoutError:
            pass
        await self._send_command(self._protocol.build_ctrl())
        await asyncio.sleep(0.05)
        await self._send_command(self._protocol.build_ctrl(echo=False))
        await asyncio.sleep(0.05)
        await self._poll()

    async def start_heating(self) -> None:
        """Start with the working HELLO5 / SETPOINT / echoed CTRL sequence."""
        async with self._operation_lock:
            await self.connect()
            await self._start_heating()

    async def _stop_heating(self) -> None:
        if self._status is None:
            await self._poll()
        await self._send_command(self._protocol.build_f4())
        await asyncio.sleep(0.05)
        await self._send_command(self._protocol.build_ctrl())
        await asyncio.sleep(0.05)
        await self._send_command(self._protocol.build_f4())
        await asyncio.sleep(0.05)
        await self._poll()

    async def stop_heating(self) -> None:
        """Stop using F4 / echoed CTRL / F4, then verify fresh status."""
        async with self._operation_lock:
            await self.connect()
            await self._stop_heating()

    async def __aenter__(self) -> CosoriKettleDevice:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.disconnect()
