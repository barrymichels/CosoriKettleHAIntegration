"""Cosori Kettle BLE device implementation."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .const import (
    COMMAND_DELAY_MS,
    HELLO_DELAY_MS,
    MAX_TEMP_C,
    MAX_TEMP_F,
    MIN_TEMP_C,
    MIN_TEMP_F,
    RX_CHAR_UUID,
    SERVICE_UUID,
    TX_CHAR_UUID,
)
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


class CosoriKettleDevice:
    """Represents a Cosori Kettle BLE device."""

    def __init__(
        self,
        device: BLEDevice,
        disconnect_callback: Callable[[BLEDevice], None] | None = None,
    ) -> None:
        """Initialize the device."""
        self._device = device
        self._client: BleakClient | None = None
        self._protocol = CosoriProtocol()
        self._disconnect_callback = disconnect_callback
        self._status: KettleStatus | None = None
        self._is_connected = False
        self._notification_event = asyncio.Event()
        self._connection_lock = asyncio.Lock()

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
        """Return if device is connected."""
        return self._is_connected and self._client is not None and self._client.is_connected

    @property
    def current_temp_c(self) -> float | None:
        """Return current temperature in Celsius."""
        if self._status is None:
            return None
        return fahrenheit_to_celsius(self._status.current_temp_f)

    @property
    def current_temp_f(self) -> float | None:
        """Return current temperature in Fahrenheit."""
        if self._status is None:
            return None
        return self._status.current_temp_f

    @property
    def target_temp_c(self) -> float | None:
        """Return target temperature in Celsius."""
        if self._status is None:
            return None
        return fahrenheit_to_celsius(self._status.target_temp_f)

    @property
    def target_temp_f(self) -> float | None:
        """Return target temperature in Fahrenheit."""
        if self._status is None:
            return None
        return self._status.target_temp_f

    @property
    def on_base(self) -> bool:
        """Return if kettle is on charging base."""
        if self._status is None:
            return False
        return self._status.on_base

    @property
    def heating(self) -> bool:
        """Return if kettle is actively heating."""
        if self._status is None:
            return False
        return self._status.heating

    def _handle_disconnect(self, client: BleakClient) -> None:
        """Handle disconnect from device."""
        _LOGGER.debug("Disconnected from %s", self.address)
        self._is_connected = False
        if self._disconnect_callback:
            self._disconnect_callback(self._device)

    def _handle_notification(self, sender: int, data: bytes) -> None:
        """Handle notification from device."""
        _LOGGER.debug("Received notification: %s", data.hex())
        status = self._protocol.parse_status(data)
        if status:
            self._status = status
            _LOGGER.debug(
                "Status update: temp=%.1f°F, target=%.1f°F, on_base=%s, heating=%s",
                status.current_temp_f,
                status.target_temp_f,
                status.on_base,
                status.heating,
            )
            self._notification_event.set()

    async def connect(self, timeout: float = 30.0) -> None:
        """Connect to the device."""
        async with self._connection_lock:
            if self.is_connected:
                _LOGGER.debug("Already connected to %s", self.address)
                return

            try:
                _LOGGER.debug("Connecting to %s", self.address)
                self._client = BleakClient(
                    self._device,
                    disconnected_callback=self._handle_disconnect,
                    timeout=timeout,
                )
                await self._client.connect()
                self._is_connected = True
                _LOGGER.info("Connected to %s", self.address)

                # Start notifications
                await self._client.start_notify(
                    RX_CHAR_UUID, self._handle_notification
                )
                _LOGGER.debug("Started notifications on %s", RX_CHAR_UUID)

                # Send registration handshake (HELLO_MIN)
                await self._send_hello_handshake()
                _LOGGER.debug("Registration handshake complete")

            except BleakError as err:
                self._is_connected = False
                raise CosoriKettleConnectionError(
                    f"Failed to connect to {self.address}: {err}"
                ) from err
            except asyncio.TimeoutError as err:
                self._is_connected = False
                raise CosoriKettleTimeoutError(
                    f"Timeout connecting to {self.address}"
                ) from err

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        async with self._connection_lock:
            if not self._client:
                return

            try:
                if self._client.is_connected:
                    await self._client.stop_notify(RX_CHAR_UUID)
                    await self._client.disconnect()
                _LOGGER.info("Disconnected from %s", self.address)
            except BleakError as err:
                _LOGGER.warning("Error disconnecting from %s: %s", self.address, err)
            finally:
                self._is_connected = False
                self._client = None

    async def _send_hello_handshake(self) -> None:
        """Send HELLO_MIN registration handshake."""
        if not self._client or not self._client.is_connected:
            raise CosoriKettleConnectionError("Not connected")

        packets = self._protocol.build_hello_min()
        for i, packet in enumerate(packets):
            _LOGGER.debug("Sending HELLO_MIN packet %d/%d: %s", i + 1, len(packets), packet.hex())
            await self._client.write_gatt_char(TX_CHAR_UUID, packet, response=False)
            if i < len(packets) - 1:
                await asyncio.sleep(HELLO_DELAY_MS / 1000.0)

    async def _send_command(self, data: bytes) -> None:
        """Send command to device."""
        if not self._client or not self._client.is_connected:
            raise CosoriKettleConnectionError("Not connected")

        _LOGGER.debug("Sending command: %s", data.hex())
        await self._client.write_gatt_char(TX_CHAR_UUID, data, response=False)

    async def update(self) -> None:
        """Poll device for status update."""
        if not self.is_connected:
            await self.connect()

        poll_cmd = self._protocol.build_poll()
        await self._send_command(poll_cmd)

        # Wait for notification with timeout
        try:
            self._notification_event.clear()
            await asyncio.wait_for(self._notification_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout waiting for status update from %s", self.address)

    async def set_target_temperature(self, temp_c: float) -> None:
        """Set target temperature in Celsius."""
        if not MIN_TEMP_C <= temp_c <= MAX_TEMP_C:
            raise CosoriKettleError(
                f"Temperature {temp_c}°C out of range ({MIN_TEMP_C}-{MAX_TEMP_C}°C)"
            )

        if not self.is_connected:
            await self.connect()

        # Convert to Fahrenheit and round to nearest integer
        temp_f = round(celsius_to_fahrenheit(temp_c))
        temp_f = max(MIN_TEMP_F, min(MAX_TEMP_F, temp_f))

        _LOGGER.info("Setting target temperature to %d°F (%.1f°C)", temp_f, temp_c)

        # Send command sequence: HELLO5 -> SETPOINT -> CTRL
        await self._send_command(self._protocol.build_hello5())
        await asyncio.sleep(COMMAND_DELAY_MS / 1000.0)

        await self._send_command(self._protocol.build_setpoint(temp_f))
        await asyncio.sleep(COMMAND_DELAY_MS / 1000.0)

        await self._send_command(self._protocol.build_ctrl(start=True))

        # Request updated status
        await asyncio.sleep(0.5)
        await self.update()

    async def start_heating(self) -> None:
        """Start heating to current target temperature."""
        if not self.is_connected:
            await self.connect()

        if self._status is None or self._status.target_temp_f == 0:
            raise CosoriKettleError("No target temperature set")

        _LOGGER.info("Starting heating to %.1f°F", self._status.target_temp_f)

        # Send control command to start
        await self._send_command(self._protocol.build_hello5())
        await asyncio.sleep(COMMAND_DELAY_MS / 1000.0)

        await self._send_command(
            self._protocol.build_setpoint(int(self._status.target_temp_f))
        )
        await asyncio.sleep(COMMAND_DELAY_MS / 1000.0)

        await self._send_command(self._protocol.build_ctrl(start=True))

        # Request updated status
        await asyncio.sleep(0.5)
        await self.update()

    async def stop_heating(self) -> None:
        """Stop heating."""
        if not self.is_connected:
            await self.connect()

        _LOGGER.info("Stopping heating")

        await self._send_command(self._protocol.build_ctrl(start=False))

        # Request updated status
        await asyncio.sleep(0.5)
        await self.update()

    async def __aenter__(self) -> CosoriKettleDevice:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
