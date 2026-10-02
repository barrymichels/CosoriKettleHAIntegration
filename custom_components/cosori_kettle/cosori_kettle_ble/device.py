"""Persistent Cosori BLE connection and serialized command transactions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import TracebackType

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import (
    CTRL_DELAY_S,
    HANDSHAKE_DELAY_S,
    HELLO5_DELAY_S,
    MAX_TEMP_C,
    MIN_TEMP_C,
    RX_CHAR_UUID,
    SETPOINT_GAP_DELAY_S,
    STATUS_CONFIRM_TIMEOUT_S,
    TX_CHAR_UUID,
)
from .exceptions import (
    CosoriKettleConnectionError,
    CosoriKettleError,
    CosoriKettleTimeoutError,
    CosoriKettleUnconfirmedError,
)
from .protocol import (
    CosoriProtocol,
    KettleStatus,
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
)

_LOGGER = logging.getLogger(__name__)
CONNECT_TIMEOUT = 30.0
COMMAND_CONNECT_TIMEOUT = 10.0
DISCONNECT_TIMEOUT = 5.0
STATUS_TIMEOUT = 5.0
# A base-dependent poll must not consume the caller's whole command budget
# waiting for an extended frame a compact-only stream never sends.
BASE_STATUS_TIMEOUT = 10.0
DISCONNECT_LOCK_TIMEOUT = 5.0


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
        self._staged_target_f: int | None = None
        self._staged_target_written = False
        self._reported_target_f: float | None = None
        self._ready = False
        self._notifications_received = 0
        self._base_received = False
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
    def reported_target_f(self) -> float | None:
        """The setpoint the kettle itself reports being armed to."""
        return self._reported_target_f

    @property
    def reported_target_c(self) -> float | None:
        temp = self.reported_target_f
        return fahrenheit_to_celsius(temp) if temp is not None else None

    @property
    def pending_target_f(self) -> int | None:
        """A staged target the kettle has not confirmed or contradicted yet."""
        return self._staged_target_f

    @property
    def pending_target_c(self) -> float | None:
        temp = self._staged_target_f
        return fahrenheit_to_celsius(temp) if temp is not None else None

    @property
    def requested_target_f(self) -> float | None:
        """Staged target until the kettle confirms or contradicts it."""
        if self._staged_target_f is not None:
            return float(self._staged_target_f)
        return self._reported_target_f

    @property
    def requested_target_c(self) -> float | None:
        temp = self.requested_target_f
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
            if status.includes_base:
                self._base_received = True
            _LOGGER.debug(
                "Kettle %s: temperature=%s°F, setpoint=%s°F, on_base=%s, heating=%s",
                self.address,
                status.current_temp_f,
                status.target_temp_f,
                status.on_base,
                status.heating,
            )
            if status.target_temp_f is not None:
                self._reported_target_f = status.target_temp_f
                self._reconcile_staged_target(status.target_temp_f)
            self._notification_event.set()

    def _reconcile_staged_target(self, reported_f: float) -> None:
        """Stop shadowing the kettle once its answer is known."""
        if self._staged_target_f is None:
            return
        if round(reported_f) == self._staged_target_f:
            # The kettle echoed the request back, so it is confirmed.
            self._retire_staged_target("confirmed")
        elif self._staged_target_written:
            # The setpoint frame was written and the kettle settled elsewhere,
            # so the request failed: the kettle's reading is authoritative.
            # An unwritten staged target stays pending for the next turn on.
            self._retire_staged_target(
                f"the kettle reports {reported_f}°F instead of "
                f"{self._staged_target_f}°F"
            )

    def _retire_staged_target(self, reason: str) -> None:
        _LOGGER.debug("Kettle %s: staged target retired (%s)", self.address, reason)
        self._staged_target_f = None
        self._staged_target_written = False

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        """Serialize one transaction; a cancelled one must drop the link."""
        async with self._operation_lock:
            try:
                yield
            except asyncio.CancelledError:
                # A cancelled write leaves the link state unknown, so the next
                # attempt must resolve a fresh adapter or proxy route.
                await self._disconnect()
                raise

    async def connect(self, timeout: float = CONNECT_TIMEOUT) -> None:
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
                # establish_connection ignores a caller timeout: it applies its
                # own per-attempt timeout (20s) and retries up to four times, so
                # the caller's budget has to bound the whole retry loop here.
                async with asyncio.timeout(timeout):
                    self._client = await establish_connection(
                        BleakClientWithServiceCache,
                        self._device,
                        self.name,
                        disconnected_callback=self._handle_disconnect,
                        ble_device_callback=self._ble_device_callback,
                    )
                _LOGGER.debug(
                    "Connected to kettle %s; subscribing to status", self.address
                )
                await self._client.start_notify(RX_CHAR_UUID, self._handle_notification)
                for packet in self._handshake or self._protocol.build_hello_min():
                    await self._send_command(packet)
                    await asyncio.sleep(HANDSHAKE_DELAY_S)
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
        self._reported_target_f = None
        self._notification_event.set()
        if client is not None:
            try:
                # disconnect also removes notifications; a hung stop_notify
                # must never hold the transaction locks open.
                async with asyncio.timeout(DISCONNECT_TIMEOUT):
                    await client.disconnect()
            except (BleakError, OSError, TimeoutError):
                _LOGGER.debug("Failed to disconnect %s", self.address, exc_info=True)

    async def disconnect(self) -> None:
        """Wait briefly for active transactions, then release the connection."""
        acquired = False
        try:
            async with asyncio.timeout(DISCONNECT_LOCK_TIMEOUT):
                await self._operation_lock.acquire()
            acquired = True
        except TimeoutError:
            # HA waits only seconds for unload tasks, so a longer command
            # deadline must not keep the single BLE connection hostage.
            _LOGGER.debug(
                "Kettle %s: releasing connection past a busy transaction",
                self.address,
            )
        try:
            async with self._connection_lock:
                await self._disconnect()
        finally:
            if acquired:
                self._operation_lock.release()

    async def _send_command(self, data: bytes) -> None:
        if self._client is None or not self._client.is_connected:
            raise CosoriKettleConnectionError("Kettle disconnected")
        try:
            await self._client.write_gatt_char(TX_CHAR_UUID, data, response=False)
        except (BleakError, OSError, TimeoutError) as err:
            await self._disconnect()
            raise CosoriKettleConnectionError(
                f"Could not write command: {err}"
            ) from err

    async def _wait_status(
        self, require_base: bool = False, timeout: float = STATUS_TIMEOUT
    ) -> None:
        try:
            await asyncio.wait_for(self._notification_event.wait(), timeout)
        except TimeoutError as err:
            await self._disconnect()
            raise CosoriKettleTimeoutError(
                self._status_timeout_message(require_base)
            ) from err
        if not self.is_connected or self._status is None:
            raise CosoriKettleConnectionError(
                "Kettle disconnected while awaiting status"
            )

    def _status_timeout_message(self, require_base: bool) -> str:
        """Name the frame a timed-out poll was waiting for."""
        missing = (
            "extended status (with the base field)"
            if require_base
            else "valid kettle status"
        )
        return (
            f"No {missing} received from {self.address} "
            f"({self._notifications_received} BLE notifications "
            "received during poll)"
        )

    async def _poll(self, require_base: bool = False) -> None:
        _LOGGER.debug("Kettle %s: requesting fresh status", self.address)
        self._notifications_received = 0
        self._base_received = False
        self._notification_event.clear()
        await self._send_command(self._protocol.build_poll())
        timeout = BASE_STATUS_TIMEOUT if require_base else None
        try:
            async with asyncio.timeout(timeout):
                # A compact status carries no base field, so a base-dependent
                # decision must see an extended frame during this poll. Track
                # it on receipt: a later compact frame overwrites the latest
                # status.
                while True:
                    await self._wait_status(require_base)
                    if not require_base or self._base_received:
                        return
                    self._notification_event.clear()
        except TimeoutError as err:
            # The bounded base-wait expired, so the required extended frame
            # never arrived: report it instead of claiming an unconfirmed
            # write at the caller's deadline.
            await self._disconnect()
            raise CosoriKettleTimeoutError(
                self._status_timeout_message(require_base)
            ) from err

    async def update(
        self,
        connect_timeout: float = CONNECT_TIMEOUT,
        poll_timeout: float | None = None,
    ) -> None:
        """Poll and require a fresh valid status; never accept stale data.

        The deadline bounds the I/O inside the transaction, so waiting for
        another transaction to finish cannot consume it.
        """
        async with self._transaction():
            try:
                async with asyncio.timeout(poll_timeout):
                    await self.connect(connect_timeout)
                    await self._poll()
            except TimeoutError as err:
                # The deadline cancelled mid-I/O, so the link state is unknown.
                await self._disconnect()
                raise CosoriKettleTimeoutError(
                    f"Status transaction did not finish within {poll_timeout}s"
                ) from err

    async def set_target_temperature(
        self, temp_c: float, *, start: bool | None = None
    ) -> bool:
        """Stage/apply a target and return whether fresh status was received."""
        if not MIN_TEMP_C <= temp_c <= MAX_TEMP_C:
            raise CosoriKettleError(f"Temperature must be {MIN_TEMP_C}-{MAX_TEMP_C}°C")
        async with self._transaction():
            self._staged_target_f = round(celsius_to_fahrenheit(temp_c))
            self._staged_target_written = False
            await self.connect(COMMAND_CONNECT_TIMEOUT)
            if start is False:
                await self._stop_heating()
                return True
            # Fresh status must precede the decision: cached heating state can
            # predate a manual stop at the kettle, and the base interlock needs
            # a frame that actually carries the base field.
            await self._poll(require_base=True)
            if start is True or self.heating:
                await self._start_heating()
                return True
            return False

    async def _start_heating(self) -> None:
        if self._status is None or not self._status.includes_base:
            await self._poll(require_base=True)
        if self.on_base is not True:
            raise CosoriKettleError("Place the kettle on its base before heating")
        target_f = (
            self._staged_target_f
            if self._staged_target_f is not None
            else self._reported_target_f
        )
        if target_f is None:
            raise CosoriKettleError("Set a target temperature before heating")
        await self._send_command(self._protocol.build_hello5())
        await asyncio.sleep(HELLO5_DELAY_S)
        self._notification_event.clear()
        await self._send_command(self._protocol.build_setpoint(round(target_f)))
        # From here the kettle owns the request: a later status frame reporting a
        # different setpoint proves the kettle did not accept it.
        self._staged_target_written = True
        await asyncio.sleep(SETPOINT_GAP_DELAY_S)
        # The working implementation permits control after a short status wait.
        try:
            await asyncio.wait_for(
                self._notification_event.wait(), STATUS_CONFIRM_TIMEOUT_S
            )
        except TimeoutError:
            pass
        await self._send_command(self._protocol.build_ctrl())
        await asyncio.sleep(CTRL_DELAY_S)
        await self._send_command(self._protocol.build_ctrl(echo=False))
        await asyncio.sleep(CTRL_DELAY_S)
        await self._verify_status("heating")

    async def start_heating(self) -> None:
        """Start with the working HELLO5 / SETPOINT / echoed CTRL sequence."""
        async with self._transaction():
            await self.connect(COMMAND_CONNECT_TIMEOUT)
            await self._poll(require_base=True)
            await self._start_heating()

    async def _stop_heating(self) -> None:
        if self._status is None:
            await self._poll()
        await self._send_command(self._protocol.build_f4())
        await asyncio.sleep(CTRL_DELAY_S)
        await self._send_command(self._protocol.build_ctrl())
        await asyncio.sleep(CTRL_DELAY_S)
        await self._send_command(self._protocol.build_f4())
        await asyncio.sleep(CTRL_DELAY_S)
        await self._verify_status("stop")

    async def _verify_status(self, action: str) -> None:
        """Confirm a written command with fresh status, or report it unconfirmed."""
        try:
            await self._poll()
        except (CosoriKettleTimeoutError, CosoriKettleConnectionError) as err:
            raise CosoriKettleUnconfirmedError(
                f"The {action} command was written, but the kettle reported no "
                "status afterwards, so its outcome is unconfirmed"
            ) from err

    async def stop_heating(self) -> None:
        """Stop using F4 / echoed CTRL / F4, then verify fresh status."""
        async with self._transaction():
            await self.connect(COMMAND_CONNECT_TIMEOUT)
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
