"""Protocol implementation for Cosori Kettle BLE communication."""

from __future__ import annotations

import logging
import struct
from typing import NamedTuple

from .const import (
    FRAME_TYPE_COMPACT,
    FRAME_TYPE_EXTENDED,
    MAX_VALID_READING_F,
    MIN_VALID_READING_F,
    MODE_BOIL,
    MODE_CUSTOM,
    OFF_BASE,
    ON_BASE,
    PACKET_HEADER,
    STAGE_IDLE,
)

_LOGGER = logging.getLogger(__name__)


class KettleStatus(NamedTuple):
    """Status data from kettle."""

    current_temp_f: float
    target_temp_f: float
    on_base: bool
    heating: bool


class CosoriProtocol:
    """Handles Cosori Kettle BLE protocol."""

    def __init__(self) -> None:
        """Initialize protocol handler."""
        self._tx_seq = 0
        self._last_rx_seq = 0
        self._last_status_seq = 0

    def _next_tx_seq(self) -> int:
        """Get next TX sequence number."""
        seq = self._tx_seq
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return seq

    @staticmethod
    def _calculate_checksum(data: bytes) -> int:
        """Calculate packet checksum (XOR of all bytes)."""
        checksum = 0
        for byte in data:
            checksum ^= byte
        return checksum

    def _build_packet(
        self, frame_type: int, payload: bytes
    ) -> bytes:
        """Build A5 packet with header, type, sequence, length, checksum, and payload."""
        seq = self._next_tx_seq()
        payload_len = len(payload)
        len_low = payload_len & 0xFF
        len_high = (payload_len >> 8) & 0xFF

        # Build packet: [HEADER] [TYPE] [SEQ] [LEN_LOW] [LEN_HIGH] [CHECKSUM] [PAYLOAD...]
        packet_without_checksum = bytes([
            PACKET_HEADER,
            frame_type,
            seq,
            len_low,
            len_high,
        ])

        checksum = self._calculate_checksum(packet_without_checksum + payload)
        packet = packet_without_checksum + bytes([checksum]) + payload

        return packet

    def build_hello_min(self) -> list[bytes]:
        """Build HELLO_MIN registration handshake (3 packets with 80ms delay)."""
        # These are the registration sequences from the ESPHome implementation
        packets = [
            bytes([0x55, 0xAA, 0x00, 0x1E, 0x00, 0x00, 0x00, 0x73]),
            bytes([0x55, 0xAA, 0x00, 0x1E, 0x01, 0x00, 0x00, 0x72]),
            bytes([0x55, 0xAA, 0x00, 0x1E, 0x02, 0x00, 0x00, 0x71]),
        ]
        return packets

    def build_poll(self) -> bytes:
        """Build polling command to request status."""
        # Poll command uses frame type 0x02
        payload = bytes([0x00])
        return self._build_packet(0x02, payload)

    def build_hello5(self) -> bytes:
        """Build HELLO5 command (sent before setpoint/control)."""
        payload = bytes([0x00, 0xF2, 0xA3, 0x00, 0x00, 0x01, 0x10, 0x0E])
        return self._build_packet(0x05, payload)

    def build_setpoint(self, temp_f: int, mode: int | None = None) -> bytes:
        """Build setpoint command."""
        if mode is None:
            mode = MODE_BOIL if temp_f >= 212 else MODE_CUSTOM

        payload = bytes([0x00, 0xF0, 0xA3, 0x00, mode, temp_f, 0x01, 0x10, 0x0E])
        return self._build_packet(0x05, payload)

    def build_ctrl(self, start: bool = True) -> bytes:
        """Build control command (start/stop heating)."""
        if start:
            payload = bytes([0x00, 0x41, 0x40, 0x00])
        else:
            payload = bytes([0x00, 0x41, 0x00, 0x00])
        return self._build_packet(0x05, payload)

    def parse_status(self, data: bytes) -> KettleStatus | None:
        """Parse status packet from kettle."""
        if len(data) < 6:
            _LOGGER.debug("Packet too short: %d bytes", len(data))
            return None

        if data[0] != PACKET_HEADER:
            _LOGGER.debug("Invalid packet header: 0x%02x", data[0])
            return None

        frame_type = data[1]
        seq = data[2]
        len_low = data[3]
        len_high = data[4]
        checksum = data[5]

        payload_len = len_low | (len_high << 8)
        expected_len = 6 + payload_len

        if len(data) < expected_len:
            _LOGGER.debug(
                "Incomplete packet: got %d bytes, expected %d", len(data), expected_len
            )
            return None

        # Verify checksum
        packet_without_checksum = data[:5] + data[6:expected_len]
        calculated_checksum = self._calculate_checksum(packet_without_checksum)

        if checksum != calculated_checksum:
            _LOGGER.warning(
                "Checksum mismatch: got 0x%02x, expected 0x%02x",
                checksum,
                calculated_checksum,
            )
            return None

        payload = data[6:expected_len]
        self._last_rx_seq = seq

        if frame_type == FRAME_TYPE_COMPACT:
            return self._parse_compact_status(payload)
        elif frame_type == FRAME_TYPE_EXTENDED:
            return self._parse_extended_status(payload)
        else:
            _LOGGER.debug("Unknown frame type: 0x%02x", frame_type)
            return None

    def _parse_compact_status(self, payload: bytes) -> KettleStatus | None:
        """Parse compact status (0x22) - 12 bytes."""
        if len(payload) < 12:
            _LOGGER.debug("Compact status payload too short: %d bytes", len(payload))
            return None

        # Based on ESPHome implementation
        current_temp_f = float(payload[4])
        target_temp_f = float(payload[5])
        stage = payload[6]

        # Validate temperature reading
        if not (MIN_VALID_READING_F <= current_temp_f <= MAX_VALID_READING_F):
            _LOGGER.debug(
                "Invalid temperature reading: %.1f°F (valid range: %d-%d°F)",
                current_temp_f,
                MIN_VALID_READING_F,
                MAX_VALID_READING_F,
            )
            return None

        heating = stage != STAGE_IDLE
        on_base = True  # Compact status doesn't include on-base info, assume on base

        return KettleStatus(
            current_temp_f=current_temp_f,
            target_temp_f=target_temp_f,
            on_base=on_base,
            heating=heating,
        )

    def _parse_extended_status(self, payload: bytes) -> KettleStatus | None:
        """Parse extended status (0x12) - 29 bytes."""
        if len(payload) < 29:
            _LOGGER.debug("Extended status payload too short: %d bytes", len(payload))
            return None

        # Based on ESPHome implementation
        current_temp_f = float(payload[4])
        target_temp_f = float(payload[5])
        stage = payload[6]
        on_base_byte = payload[14]

        # Validate temperature reading
        if not (MIN_VALID_READING_F <= current_temp_f <= MAX_VALID_READING_F):
            _LOGGER.debug(
                "Invalid temperature reading: %.1f°F (valid range: %d-%d°F)",
                current_temp_f,
                MIN_VALID_READING_F,
                MAX_VALID_READING_F,
            )
            return None

        heating = stage != STAGE_IDLE
        on_base = on_base_byte == ON_BASE

        return KettleStatus(
            current_temp_f=current_temp_f,
            target_temp_f=target_temp_f,
            on_base=on_base,
            heating=heating,
        )


def fahrenheit_to_celsius(temp_f: float) -> float:
    """Convert Fahrenheit to Celsius."""
    return (temp_f - 32) * 5 / 9


def celsius_to_fahrenheit(temp_c: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return temp_c * 9 / 5 + 32
