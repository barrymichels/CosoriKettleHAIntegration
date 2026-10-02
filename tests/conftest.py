"""A BLE test double; Home Assistant itself is provided by its test plugin."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from bleak.backends.device import BLEDevice
from cosori_kettle_ble.protocol import CosoriProtocol
from test_protocol import OFF_BASE, ON_BASE


class KettleClient:
    """Simulate GATT notifications, including responses during writes."""

    def __init__(self):
        self.is_connected = True
        self.writes = []
        self.notify = None
        self.heating = False
        self.stopping = False
        self.target = 212
        self.respond = True
        self.respond_poll = True
        self.poll_responses_left: int | None = None
        self.on_base = True
        self.disconnect = AsyncMock(side_effect=self._disconnect)
        self.start_notify = AsyncMock(side_effect=self._subscribe)

    def _disconnect(self):
        self.is_connected = False

    def _subscribe(self, characteristic, notify):
        assert characteristic == "0000fff1-0000-1000-8000-00805f9b34fb"
        # establish_connection hands back a fresh client, so a new
        # subscription always arrives on a live connection.
        self.is_connected = True
        self.notify = notify

    def status(self):
        packet = bytearray(ON_BASE if self.on_base else OFF_BASE)
        packet[10] = int(self.heating)
        packet[12] = self.target
        packet[5] = CosoriProtocol._calculate_checksum(bytes(packet[:5] + packet[6:]))
        # Real extended responses exceed the default 20-byte notification payload.
        self.notify(None, packet[:20])
        self.notify(None, packet[20:])

    async def write_gatt_char(self, characteristic, packet, response):
        assert characteristic == "0000fff2-0000-1000-8000-00805f9b34fb"
        assert response is False
        self.writes.append(packet)
        await asyncio.sleep(0)
        if len(packet) < 6:
            return
        payload = packet[6:]
        if payload[:4] == bytes.fromhex("00f0a300"):
            self.target = payload[5]
        elif payload[:4] == bytes.fromhex("00f2a300"):
            # HELLO5 prepares a new heating session, ending a prior stop.
            self.stopping = False
        elif payload == bytes.fromhex("00f4a300"):
            self.stopping = True
            self.heating = False
        elif packet[1] == 0x12 and payload == bytes.fromhex("00414000"):
            self.heating = not self.stopping
        if payload == bytes.fromhex("00404000") and self.respond_poll:
            if self.poll_responses_left is not None:
                if self.poll_responses_left <= 0:
                    return
                self.poll_responses_left -= 1
            self.status()
        elif self.respond and payload[:4] == bytes.fromhex("00f0a300"):
            self.status()


@pytest.fixture
def ble_device():
    return BLEDevice("AA:BB:CC:DD:EE:FF", "Cosori Kettle", {})


@pytest.fixture
def kettle_client():
    return KettleClient()
