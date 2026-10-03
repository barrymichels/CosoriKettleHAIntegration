"""Exercise real transaction code against simulated BLE notifications."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from bleak.exc import BleakError
from conftest import KettleClient
from cosori_kettle_ble.device import CosoriKettleDevice
from cosori_kettle_ble.exceptions import (
    CosoriKettleError,
    CosoriKettleTimeoutError,
    CosoriKettleUnconfirmedError,
)
from test_protocol import COMPACT


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
    assert device.reported_target_f == 212
    assert device.on_base is True
    assert kettle_client.writes[3].hex() == "a522010400b300404000"


async def test_start_stop_match_working_transactions(device, kettle_client):
    await device.update()
    kettle_client.writes.clear()
    assert await device.set_target_temperature(100) is False
    # A temperature-only request still polls fresh status before deciding.
    assert [packet[6:10].hex() for packet in kettle_client.writes] == ["00404000"]
    kettle_client.writes.clear()
    await device.start_heating()
    assert [packet[6:10].hex() for packet in kettle_client.writes] == [
        "00404000",  # fresh status before the start transaction
        "00f2a300",
        "00f0a300",
        "00414000",
        "00414000",
        "00404000",  # verification poll
    ]
    assert device.heating is True
    kettle_client.writes.clear()
    await device.stop_heating()
    assert [packet[6:10].hex() for packet in kettle_client.writes] == [
        "00f4a300",
        "00414000",
        "00f4a300",
        "00404000",
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
        "00404000",  # start_heating's fresh-status poll
        "00f2a300",
        "00f0a300",
        "00414000",
        "00414000",
        "00404000",  # start verification poll
        "00404000",  # the queued update poll runs after the transaction
    ]


async def test_status_timeout_disconnects(device, kettle_client):
    await device.update()
    kettle_client.respond = False
    kettle_client.respond_poll = False
    original = device._wait_status

    async def short_wait(require_base: bool = False):
        await original(require_base, timeout=0.01)

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


async def test_reported_target_follows_the_kettle(device, kettle_client):
    """A setpoint changed on the kettle must not latch behind the first read."""
    await device.update()
    assert device.reported_target_f == 212
    assert device.requested_target_f == 212

    kettle_client.target = 185
    await device.update()
    assert device.reported_target_f == 185


async def test_staged_target_is_retired_once_confirmed(device, kettle_client):
    """Staging shows an unwritten target, but confirmation hands control back."""
    await device.update()
    assert await device.set_target_temperature(80) is False
    assert device.requested_target_f == 176
    assert device.reported_target_f == 212
    assert kettle_client.target == 212

    await device.start_heating()
    assert kettle_client.target == 176
    assert device.pending_target_f is None
    assert device.requested_target_f == 176

    kettle_client.target = 185
    await device.update()
    assert device.reported_target_f == 185


async def test_spontaneous_disconnect_clears_reported_target_only(
    device, kettle_client
):
    await device.update()
    assert device.reported_target_f == 212
    assert await device.set_target_temperature(80) is False
    assert device.pending_target_f == 176

    device._handle_disconnect(device._client)

    assert device.reported_target_f is None
    assert device.pending_target_f == 176
    assert device.requested_target_f == 176


async def test_unconfirmed_command_reports_the_outcome(device, kettle_client):
    """A written command with no follow-up status must not be called a failure."""
    await device.update()
    # The fresh-status poll is answered; the verification poll is not.
    kettle_client.poll_responses_left = 1
    original = device._wait_status

    async def short_wait(require_base: bool = False):
        await original(require_base, timeout=0.01)

    with patch.object(device, "_wait_status", side_effect=short_wait):
        with pytest.raises(CosoriKettleUnconfirmedError) as raised:
            await device.start_heating()

    assert "unconfirmed" in str(raised.value)
    assert kettle_client.heating is True


async def test_uncommandable_reported_target_cannot_start_heating(
    device, kettle_client
):
    """A corrupt setpoint must raise a clean error, never a raw ValueError."""
    kettle_client.target = 80
    with pytest.raises(CosoriKettleError, match="target temperature"):
        await device.start_heating()
    assert device.current_temp_f == 92
    assert device.on_base is True
    assert kettle_client.writes[-1].hex() == "a522010400b300404000"


async def test_cancelled_poll_write_drops_the_wedged_client(ble_device, kettle_client):
    """A cancelled transaction must not leave a client marked connected."""
    started = asyncio.Event()
    original = kettle_client.write_gatt_char

    async def hanging_poll_write(characteristic, packet, response):
        if packet[6:10] == bytes.fromhex("00404000"):
            started.set()
            await asyncio.Future()
        await original(characteristic, packet, response)

    kettle_client.write_gatt_char = hanging_poll_write
    device = CosoriKettleDevice(ble_device)
    with patch(
        "cosori_kettle_ble.device.establish_connection",
        AsyncMock(return_value=kettle_client),
    ):
        task = asyncio.create_task(device.update())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert kettle_client.disconnect.await_count == 1
    assert device.is_connected is False

    recovered = KettleClient()
    with patch(
        "cosori_kettle_ble.device.establish_connection",
        AsyncMock(return_value=recovered),
    ) as connect:
        await device.update()
    assert connect.await_count == 1
    assert device.current_temp_f == 92
    await device.disconnect()


async def test_hung_disconnect_cannot_hold_the_connection_lock(
    ble_device, kettle_client
):
    """A deadline must not hand control to an unresponsive disconnect."""
    started = asyncio.Event()

    async def pending_subscription(*args, **kwargs):
        started.set()
        await asyncio.Future()

    async def hanging_disconnect():
        await asyncio.Future()

    kettle_client.start_notify.side_effect = pending_subscription
    kettle_client.disconnect = AsyncMock(side_effect=hanging_disconnect)
    device = CosoriKettleDevice(ble_device)
    with (
        patch(
            "cosori_kettle_ble.device.establish_connection",
            AsyncMock(return_value=kettle_client),
        ),
        patch("cosori_kettle_ble.device.DISCONNECT_TIMEOUT", 0.05),
    ):
        task = asyncio.create_task(device.connect())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2.0)
    assert device._connection_lock.locked() is False
    assert device.is_connected is False


async def test_written_but_unconfirmed_target_is_superseded_by_the_kettle(
    device, kettle_client
):
    """A setpoint the kettle never accepted must stop shadowing its reading."""
    await device.update()
    assert device.requested_target_f == 212

    kettle_client.respond = False
    # The fresh-status poll is answered; later polls are not.
    kettle_client.poll_responses_left = 1
    original = device._wait_status

    async def short_wait(require_base: bool = False):
        await original(require_base, timeout=0.01)

    with patch.object(device, "_wait_status", side_effect=short_wait):
        with pytest.raises(CosoriKettleUnconfirmedError):
            await device.set_target_temperature(80, start=True)

    recovered = KettleClient()
    with patch(
        "cosori_kettle_ble.device.establish_connection",
        AsyncMock(return_value=recovered),
    ):
        await device.update()

    assert recovered.target == 212
    assert device.reported_target_f == 212
    assert device.requested_target_f == 212


async def test_unwritten_staged_target_survives_a_refused_start(device, kettle_client):
    """A start refused before any write keeps the staged target for later."""
    await device.update()
    assert await device.set_target_temperature(80) is False
    assert device.requested_target_f == 176

    kettle_client.on_base = False
    await device.update()
    assert device.requested_target_f == 176
    with pytest.raises(CosoriKettleError, match="on its base"):
        await device.start_heating()
    assert kettle_client.target == 212

    kettle_client.on_base = True
    await device.update()
    await device.start_heating()
    assert kettle_client.target == 176
    assert device.requested_target_f == 176


async def test_temperature_only_request_after_manual_stop_does_not_start(
    device, kettle_client
):
    """Cached heating must not start boiling after a stop at the kettle."""
    await device.update()
    await device.start_heating()
    assert device.heating is True
    kettle_client.heating = False  # someone pressed the kettle's own button
    kettle_client.writes.clear()
    assert await device.set_target_temperature(80) is False
    assert [packet[6:10].hex() for packet in kettle_client.writes] == ["00404000"]
    assert kettle_client.heating is False


async def test_restart_after_stop_works(device, kettle_client):
    """HELLO5 ends a prior stop, so a stopped kettle can heat again."""
    await device.update()
    await device.start_heating()
    await device.stop_heating()
    assert device.heating is False
    await device.start_heating()
    assert device.heating is True


async def test_compact_notification_updates_heating_and_keeps_base(
    device, kettle_client
):
    """Compact frames carry no base field, so cached base state persists."""
    await device.update()
    assert device.on_base is True
    kettle_client.notify(None, COMPACT)
    assert device.heating is True
    assert device.current_temp_f == 100
    assert device.on_base is True


async def test_compact_followup_does_not_lose_fresh_base_status(device, kettle_client):
    """An extended response followed by a compact one still satisfies the
    base requirement for starting."""
    await device.update()
    original = kettle_client.status

    def respond_with_extended_then_compact():
        original()
        kettle_client.notify(None, COMPACT)

    kettle_client.status = respond_with_extended_then_compact
    await device.start_heating()
    assert device.heating is True


async def test_start_heating_without_fresh_base_sends_nothing(device, kettle_client):
    """Compact-only notifications carry no base field: the heating decision
    must fail with no heating command written."""
    original = device._wait_status

    async def short_wait(require_base: bool = False):
        await original(require_base, timeout=0.01)

    def compact():
        kettle_client.notify(None, COMPACT[:10])
        kettle_client.notify(None, COMPACT[10:])

    kettle_client.status = compact
    await device.update()
    assert device.current_temp_f == 100
    assert device.on_base is None
    kettle_client.writes.clear()
    with patch.object(device, "_wait_status", side_effect=short_wait):
        with pytest.raises(CosoriKettleTimeoutError, match="extended status"):
            await device.start_heating()
    assert kettle_client.writes[-1][6:10].hex() == "00404000"
    assert kettle_client.heating is False
    assert device.on_base is None


async def test_compact_only_stream_hits_the_bounded_base_wait(
    device, kettle_client, monkeypatch
):
    """Compact frames that keep arriving must hit the bounded base-wait, not
    the caller's deadline: no heating command is written."""
    monkeypatch.setattr("cosori_kettle_ble.device.BASE_STATUS_TIMEOUT", 0.01)

    async def stream():
        while True:
            if kettle_client.notify is not None:
                kettle_client.notify(None, COMPACT)
            await asyncio.sleep(0.001)

    kettle_client.respond = False
    kettle_client.respond_poll = False
    producer = asyncio.create_task(stream())
    try:
        async with asyncio.timeout(2.0):
            with pytest.raises(CosoriKettleTimeoutError, match="extended status"):
                await device.start_heating()
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
    assert kettle_client.writes[-1][6:10].hex() == "00404000"
    assert kettle_client.heating is False
    assert device.on_base is None


async def test_connect_deadline_binds_regardless_of_the_connector(ble_device):
    """establish_connection ignores a caller timeout, so the device bounds it."""

    async def slow_connection(*args, **kwargs):
        await asyncio.sleep(5)

    device = CosoriKettleDevice(ble_device)
    with patch("cosori_kettle_ble.device.establish_connection", slow_connection):
        with pytest.raises(CosoriKettleTimeoutError):
            await device.connect(timeout=0.05)
    assert device.is_connected is False
