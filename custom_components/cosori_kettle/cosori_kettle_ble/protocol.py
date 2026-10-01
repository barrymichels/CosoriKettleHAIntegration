"""Cosori wire protocol, matching the working ESPHome component."""

from __future__ import annotations

from typing import NamedTuple

from .const import (
    FRAME_TYPE_COMPACT,
    FRAME_TYPE_EXTENDED,
    MAX_VALID_READING_F,
    MIN_VALID_READING_F,
    MODE_BOIL,
    MODE_CUSTOM,
    PACKET_HEADER,
)


class KettleStatus(NamedTuple):
    """Status received from the kettle (temperatures are Fahrenheit)."""

    current_temp_f: float
    target_temp_f: float
    on_base: bool | None
    heating: bool


class CosoriProtocol:
    """Build commands and assemble status frames from BLE notifications."""

    def __init__(self) -> None:
        self._tx_seq = 0
        self._last_rx_seq = 0
        self._last_status_seq = 0
        self._on_base: bool | None = None
        self._buffer = bytearray()

    def _next_tx_seq(self) -> int:
        # Match ESPHome's increment-before-use and RX synchronization on wrap.
        if self._tx_seq == 0 and self._last_rx_seq != 0:
            self._tx_seq = (self._last_rx_seq + 1) & 0xFF
        else:
            self._tx_seq = (self._tx_seq + 1) & 0xFF
        return self._tx_seq

    @staticmethod
    def _calculate_checksum(data: bytes) -> int:
        """A complete frame sums to 0xFF modulo 256."""
        return (0xFF - sum(data)) & 0xFF

    def _build_packet(
        self, frame_type: int, payload: bytes, seq: int | None = None
    ) -> bytes:
        if seq is None:
            seq = self._next_tx_seq()
        header = bytes(
            [PACKET_HEADER, frame_type, seq, len(payload) & 0xFF, len(payload) >> 8]
        )
        return header + bytes([self._calculate_checksum(header + payload)]) + payload

    @staticmethod
    def build_hello_min() -> list[bytes]:
        """Default registration frame split into the same three GATT writes."""
        return [
            bytes.fromhex("a5220024008a0081d10036343238376139313765"),
            bytes.fromhex("3734366130373331313636623736663433643563"),
            bytes.fromhex("6262"),
        ]

    def build_poll(self) -> bytes:
        """Request extended status."""
        return self._build_packet(FRAME_TYPE_COMPACT, bytes.fromhex("00404000"))

    def build_hello5(self) -> bytes:
        """Prepare a new setpoint."""
        return self._build_packet(FRAME_TYPE_COMPACT, bytes.fromhex("00f2a3000001100e"))

    def build_setpoint(self, temp_f: int, mode: int | None = None) -> bytes:
        """Set the heating setpoint."""
        if not 104 <= temp_f <= 212:
            raise ValueError("Setpoint must be between 104 and 212°F")
        if mode is None:
            mode = MODE_BOIL if temp_f == 212 else MODE_CUSTOM
        payload = bytes([0x00, 0xF0, 0xA3, 0x00, mode, temp_f, 0x01, 0x10, 0x0E])
        return self._build_packet(FRAME_TYPE_COMPACT, payload)

    def build_f4(self) -> bytes:
        """Prepare or complete a stop command."""
        return self._build_packet(FRAME_TYPE_COMPACT, bytes.fromhex("00f4a300"))

    def build_ctrl(self, *, echo: bool = True) -> bytes:
        """Control uses the same payload for start and stop; F4 selects stop."""
        seq = (self._last_status_seq or self._last_rx_seq) if echo else None
        return self._build_packet(FRAME_TYPE_EXTENDED, bytes.fromhex("00414000"), seq)

    def feed(self, data: bytes | bytearray) -> list[KettleStatus]:
        """Handle fragmented, coalesced, and noisy BLE notifications."""
        self._buffer.extend(data)
        statuses: list[KettleStatus] = []
        while self._buffer:
            start = self._buffer.find(PACKET_HEADER)
            if start < 0:
                self._buffer.clear()
                break
            del self._buffer[:start]
            if len(self._buffer) < 6:
                break
            length = int.from_bytes(self._buffer[3:5], "little")
            # Kettle frames are small; reject corrupt lengths instead of retaining
            # an unbounded buffer and blocking every later notification.
            if length > 512:
                del self._buffer[0]
                continue
            frame_length = 6 + length
            if len(self._buffer) < frame_length:
                break
            packet = bytes(self._buffer[:frame_length])
            if sum(packet) & 0xFF != 0xFF:
                del self._buffer[0]
                continue
            del self._buffer[:frame_length]
            if (status := self.parse_status(packet)) is not None:
                statuses.append(status)
        return statuses

    def parse_status(self, data: bytes) -> KettleStatus | None:
        """Parse one complete frame, preserving base state on compact status."""
        if len(data) < 6 or data[0] != PACKET_HEADER:
            return None
        length = int.from_bytes(data[3:5], "little")
        if len(data) != 6 + length or sum(data) & 0xFF != 0xFF:
            return None
        self._last_rx_seq = data[2]
        payload = data[6:]
        if data[1] == FRAME_TYPE_COMPACT:
            if len(payload) < 9 or payload[:2] != b"\x01\x41":
                return None
            heating = payload[8] != 0
        elif data[1] == FRAME_TYPE_EXTENDED:
            if len(payload) < 8 or payload[:2] != b"\x01\x40":
                return None
            heating = payload[4] != 0
        else:
            return None
        if not MIN_VALID_READING_F <= payload[7] <= MAX_VALID_READING_F:
            return None
        if data[1] == FRAME_TYPE_EXTENDED and len(payload) >= 15:
            self._on_base = payload[14] == 0
        self._last_status_seq = data[2]
        return KettleStatus(
            float(payload[7]), float(payload[6]), self._on_base, heating
        )


def fahrenheit_to_celsius(temp_f: float) -> float:
    """Convert Fahrenheit to Celsius."""
    return (temp_f - 32) * 5 / 9


def celsius_to_fahrenheit(temp_c: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return temp_c * 9 / 5 + 32
