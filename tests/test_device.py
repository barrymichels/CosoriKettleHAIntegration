"""Exercise real transaction code against simulated BLE notifications."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from bleak.exc import BleakError
from cosori_kettle_ble.device import CosoriKettleDevice
from cosori_kettle_ble.exceptions import CosoriKettleError, CosoriKettleTimeoutError


@pytest.fixture
async def device(ble_device, kettle_client):
    with patch(
        "cosori_kettle_ble.device.establish_connection",
        AsyncMock(return_value=kettle_client),
    ):
        device = CosoriKettleDevice(ble_device)
        yield device
        await device.disconnect()


async def test_poll_accepts_immediate_fragmented_response(device, kettle_client):
    await device.update()
    assert device.current_temp_f == 92
    assert device.target_temp_f == 212
    assert device.on_base is True
    assert kettle_client.writes[3].hex() == "a522010400b300404000"


async def test_start_stop_match_working_transactions(device, kettle_client):
    await device.update()
    kettle_client.writes.clear()
    assert await device.set_target_temperature(100) is False
    assert kettle_client.writes == []
    await device.start_heating()
    assert [packet.hex() for packet in kettle_client.writes] == [
        "a5220208007a00f2a3000001100e",
        "a522030900a200f0a30004d401100e",
        "a512190400aa00414000",
        "a512040400bf00414000",
        "a522050400af00404000",
    ]
    assert device.heating is True
    kettle_client.writes.clear()
    await device.stop_heating()
    assert [packet.hex() for packet in kettle_client.writes] == [
        "a5220604009700f4a300",
        "a512190400aa00414000",
        "a5220704009600f4a300",
        "a522080400ac00404000",
    ]
    assert device.heating is False


async def test_stop_after_connect_polls_before_echo_control(device, kettle_client):
    await device.stop_heating()
    assert kettle_client.writes[3].hex() == "a522010400b300404000"
    assert kettle_client.writes[5].hex() == "a512190400aa00414000"


async def test_poll_cannot_interleave_start_sequence(device, kettle_client):
    await device.update()
    kettle_client.writes.clear()
    await asyncio.gather(device.start_heating(), device.update())
    assert [packet[6:10].hex() for packet in kettle_client.writes] == [
        "00f2a300",
        "00f0a300",
        "00414000",
        "00414000",
        "00404000",
        "00404000",
    ]


async def test_status_timeout_disconnects(device, kettle_client):
    await device.update()
    kettle_client.respond = False
    original = device._wait_status

    async def short_wait():
        await original(0.01)

    with patch.object(device, "_wait_status", side_effect=short_wait):
        with pytest.raises(CosoriKettleTimeoutError):
            await device.update()
    kettle_client.disconnect.assert_awaited_once()
    assert device.is_connected is False
    assert device.current_temp_c is None


async def test_notify_failure_releases_connection(ble_device, kettle_client):
    kettle_client.start_notify.side_effect = BleakError("failed subscription")
    with patch(
        "cosori_kettle_ble.device.establish_connection",
        AsyncMock(return_value=kettle_client),
    ):
        device = CosoriKettleDevice(ble_device)
        with pytest.raises(CosoriKettleError):
            await device.connect()
    kettle_client.disconnect.assert_awaited_once()


@pytest.mark.parametrize("temperature", [39, 101, float("nan"), float("inf")])
async def test_invalid_temperature_never_writes(device, kettle_client, temperature):
    with pytest.raises(CosoriKettleError):
        await device.set_target_temperature(temperature, start=True)
    assert kettle_client.writes == []


async def test_custom_handshake(ble_device, kettle_client):
    handshake = [b"first", b"second", b"third"]
    with patch(
        "cosori_kettle_ble.device.establish_connection",
        AsyncMock(return_value=kettle_client),
    ):
        device = CosoriKettleDevice(ble_device, handshake=handshake)
        await device.update()
        await device.disconnect()
    assert kettle_client.writes[:3] == handshake


async def test_cancelled_connection_can_be_retried(ble_device, kettle_client):
    """A HA reload/shutdown cancellation must propagate and release locks."""
    started = asyncio.Event()

    async def pending_connection(*args, **kwargs):
        started.set()
        await asyncio.Future()

    device = CosoriKettleDevice(ble_device)
    with patch("cosori_kettle_ble.device.establish_connection", pending_connection):
        task = asyncio.create_task(device.update())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert device.is_connected is False
    with patch(
        "cosori_kettle_ble.device.establish_connection",
        AsyncMock(return_value=kettle_client),
    ):
        await device.update()
        assert device.current_temp_f == 92
        await device.disconnect()
    kettle_client.disconnect.assert_awaited_once()


async def test_cancelled_subscription_releases_client(ble_device, kettle_client):
    """Cancellation after connect must not strand the persistent client."""
    started = asyncio.Event()

    async def pending_subscription(*args, **kwargs):
        started.set()
        await asyncio.Future()

    kettle_client.start_notify.side_effect = pending_subscription
    device = CosoriKettleDevice(ble_device)
    with patch(
        "cosori_kettle_ble.device.establish_connection",
        AsyncMock(return_value=kettle_client),
    ):
        task = asyncio.create_task(device.connect())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    kettle_client.disconnect.assert_awaited_once()
    assert device.is_connected is False
