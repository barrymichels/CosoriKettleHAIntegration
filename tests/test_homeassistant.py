"""Use real HA setup, platforms, config flows, and service validation."""

import asyncio
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")
from bleak.exc import BleakError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_ADDRESS,
    EVENT_HOMEASSISTANT_STOP,
    STATE_UNAVAILABLE,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cosori_kettle.const import CONF_HANDSHAKE, DOMAIN, SERVICE_UUID
from custom_components.cosori_kettle.cosori_kettle_ble.exceptions import (
    CosoriKettleTimeoutError,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")
BLE_MODULE = "custom_components.cosori_kettle.cosori_kettle_ble.device"


@pytest.fixture
async def entry(hass, ble_device, kettle_client):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Cosori Kettle",
        unique_id=ble_device.address,
        data={CONF_ADDRESS: ble_device.address},
    )
    entry.add_to_hass(hass)
    with (
        patch("homeassistant.setup.async_process_deps_reqs", AsyncMock()),
        patch("homeassistant.config_entries.async_process_deps_reqs", AsyncMock()),
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=ble_device,
        ),
        patch(
            f"{BLE_MODULE}.establish_connection", AsyncMock(return_value=kettle_client)
        ),
    ):
        assert await async_setup_component(hass, DOMAIN, {})
        assert entry.state is ConfigEntryState.LOADED
        await hass.async_block_till_done()
        yield entry
        if entry.state is ConfigEntryState.LOADED:
            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()


async def test_entities_and_service_controls(hass, entry, kettle_client):
    heater = hass.states.get("water_heater.cosori_kettle")
    assert heater is not None
    assert heater.state == "off"
    assert heater.attributes["current_temperature"] == pytest.approx(33.3, abs=0.1)
    assert heater.attributes["operation_list"] == ["off", "on"]
    assert hass.states.get("binary_sensor.cosori_kettle_on_base").state == "on"
    assert hass.states.get("binary_sensor.cosori_kettle_heating").state == "off"
    kettle_client.writes.clear()
    await hass.services.async_call(
        "water_heater",
        "set_temperature",
        {
            "entity_id": heater.entity_id,
            "temperature": 80,
        },
        blocking=True,
    )
    # A temperature-only request still polls fresh status before deciding.
    assert [packet[6:10].hex() for packet in kettle_client.writes] == ["00404000"]
    await hass.services.async_call(
        "water_heater",
        "set_operation_mode",
        {
            "entity_id": heater.entity_id,
            "operation_mode": "on",
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert kettle_client.target == 176
    assert kettle_client.heating is True
    assert hass.states.get(heater.entity_id).state == "on"
    await hass.services.async_call(
        "water_heater",
        "set_temperature",
        {
            "entity_id": heater.entity_id,
            "temperature": 90,
            "operation_mode": "off",
        },
        blocking=True,
    )
    assert kettle_client.heating is False
    assert entry.runtime_data.requested_target_c == pytest.approx(90)
    heater_state = hass.states.get(heater.entity_id)
    assert heater_state.attributes["temperature"] == pytest.approx(80)
    assert heater_state.attributes["requested_temperature"] == pytest.approx(90)


async def test_disconnect_staged_target_and_unload(hass, entry, kettle_client):
    coordinator = entry.runtime_data
    coordinator.device._handle_disconnect(coordinator.device._client)
    await hass.async_block_till_done()
    assert (
        hass.states.get("sensor.cosori_kettle_current_temperature").state
        == STATE_UNAVAILABLE
    )
    await coordinator.async_set_temperature(80)
    assert coordinator.last_update_success is True
    await hass.async_block_till_done()
    assert (
        hass.states.get("sensor.cosori_kettle_current_temperature").state
        != STATE_UNAVAILABLE
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert coordinator._shutdown_requested is True
    assert kettle_client.disconnect.await_count >= 1


async def test_status_poll_publishes_entities_and_recovers_availability(
    hass, entry, kettle_client
):
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coordinator = entry.runtime_data
    entity_ids = (
        "water_heater.cosori_kettle",
        "sensor.cosori_kettle_current_temperature",
        "binary_sensor.cosori_kettle_on_base",
        "binary_sensor.cosori_kettle_heating",
    )
    kettle_client.target = 185
    kettle_client.heating = True
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert all(
        hass.states.get(entity_id).state != STATE_UNAVAILABLE
        for entity_id in entity_ids
    )
    assert hass.states.get("water_heater.cosori_kettle").state == "on"
    assert hass.states.get("binary_sensor.cosori_kettle_heating").state == "on"

    coordinator.async_set_update_error(UpdateFailed("Temporary transport failure"))
    await hass.async_block_till_done()
    assert all(
        hass.states.get(entity_id).state == STATE_UNAVAILABLE
        for entity_id in entity_ids
    )

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success is True
    assert all(
        hass.states.get(entity_id).state != STATE_UNAVAILABLE
        for entity_id in entity_ids
    )
    assert hass.states.get("water_heater.cosori_kettle").state == "on"
    assert hass.states.get("binary_sensor.cosori_kettle_heating").state == "on"


async def test_validation_error_preserves_device_availability(hass, entry):
    coordinator = entry.runtime_data
    with pytest.raises(ServiceValidationError):
        await coordinator.async_set_temperature(101)
    assert coordinator.last_update_success is True
    with patch.object(
        coordinator.device,
        "start_heating",
        side_effect=CosoriKettleTimeoutError("no response"),
    ):
        with pytest.raises(HomeAssistantError):
            await coordinator.async_start_heating()
    assert coordinator.last_update_success is False


async def test_flow_manual_mac_probe_and_duplicate(hass, ble_device, kettle_client):
    with (
        patch(
            "homeassistant.components.bluetooth.async_discovered_service_info",
            return_value=[],
        ),
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=ble_device,
        ),
        patch(
            f"{BLE_MODULE}.establish_connection", AsyncMock(return_value=kettle_client)
        ),
        patch(
            "custom_components.cosori_kettle.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: "bad"}
        )
        assert result["errors"] == {CONF_ADDRESS: "invalid_address"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ble_device.address.lower()}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] == {CONF_ADDRESS: ble_device.address}
        kettle_client.disconnect.assert_awaited_once()
        assert kettle_client.heating is False
        await hass.async_block_till_done()
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        duplicate = await hass.config_entries.flow.async_configure(
            duplicate["flow_id"], {CONF_ADDRESS: ble_device.address}
        )
        assert duplicate["type"] is FlowResultType.ABORT
        assert duplicate["reason"] == "already_configured"


async def test_setup_failure_releases_connection(hass, ble_device, kettle_client):
    from custom_components.cosori_kettle import async_setup_entry
    from custom_components.cosori_kettle.coordinator import (
        CosoriKettleDataUpdateCoordinator,
    )

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_ADDRESS: ble_device.address})
    entry.add_to_hass(hass)
    entry._async_set_state(hass, ConfigEntryState.SETUP_IN_PROGRESS, None)

    async def failed_refresh(self):
        await self.device.connect()
        raise HomeAssistantError("failed first status")

    with (
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=ble_device,
        ),
        patch(
            f"{BLE_MODULE}.establish_connection", AsyncMock(return_value=kettle_client)
        ),
        patch.object(
            CosoriKettleDataUpdateCoordinator,
            "async_config_entry_first_refresh",
            failed_refresh,
        ),
    ):
        with pytest.raises(HomeAssistantError):
            await async_setup_entry(hass, entry)
    kettle_client.disconnect.assert_awaited_once()


def test_manifest_matches_core_bluetooth_dependency():
    import homeassistant.components.bluetooth as bluetooth

    manifest = json.loads(
        Path("custom_components/cosori_kettle/manifest.json").read_text()
    )
    core_manifest = json.loads(
        Path(bluetooth.__file__).with_name("manifest.json").read_text()
    )

    def names(requirements: list[str]) -> set[str]:
        return {re.split(r"[=<>!~]", item)[0] for item in requirements}

    assert manifest["iot_class"] == "local_polling"
    assert manifest["dependencies"] == ["bluetooth_adapters"]
    assert manifest["bluetooth"] == [
        {"connectable": True, "service_uuid": SERVICE_UUID}
    ]
    # A pinned requirement can conflict with the version Home Assistant core
    # already ships, so this integration must let core supply the package.
    assert manifest["requirements"] == ["bleak-retry-connector"]
    assert names(manifest["requirements"]) <= names(core_manifest["requirements"])


def test_release_version_is_consistent_across_manifests():
    import tomllib

    import cosori_kettle_ble

    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    integration_manifest = json.loads(
        Path("custom_components/cosori_kettle/manifest.json").read_text()
    )
    # One release number for the integration HACS installs, the library it
    # bundles, and the distribution metadata pip reports.
    assert cosori_kettle_ble.__version__ == pyproject["project"]["version"]
    assert integration_manifest["version"] == pyproject["project"]["version"]


async def test_ha_shutdown_releases_connection(hass, entry, kettle_client):
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert entry.runtime_data._shutdown_requested is True
    kettle_client.disconnect.assert_awaited_once()


async def test_unload_cancels_active_poll_and_releases_ble(hass, entry, kettle_client):
    """Core cancels entry-tracked refreshes on unload; BLE must still be freed."""
    coordinator = entry.runtime_data
    original = kettle_client.write_gatt_char

    async def hanging_poll_write(characteristic, packet, response):
        if packet[6:10] == bytes.fromhex("00404000"):
            await asyncio.Future()
        await original(characteristic, packet, response)

    kettle_client.write_gatt_char = hanging_poll_write
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), "test active refresh"
    )
    await asyncio.sleep(0.05)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert coordinator._shutdown_requested is True
    assert kettle_client.disconnect.await_count >= 1
    assert coordinator.device.is_connected is False


async def test_unload_cancels_active_command_and_releases_ble(
    hass, entry, kettle_client
):
    """Production COMMAND_TIMEOUT (30 s) exceeds HA's ~10 s unload wait.

    Unload must cancel the command and free BLE within its own budget
    instead of timing out with the connection still held.
    """
    coordinator = entry.runtime_data
    original = kettle_client.write_gatt_char

    async def hanging_control_write(characteristic, packet, response):
        if packet[6:10] == bytes.fromhex("00f0a300"):
            await asyncio.Future()
        await original(characteristic, packet, response)

    kettle_client.write_gatt_char = hanging_control_write
    command = asyncio.create_task(coordinator.async_start_heating())
    await asyncio.sleep(0.05)
    async with asyncio.timeout(5):
        assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert command.cancelled()
    assert kettle_client.disconnect.await_count >= 1
    assert coordinator.device.is_connected is False


async def test_ha_shutdown_during_active_poll_releases_ble(hass, entry, kettle_client):
    """A poll in flight at HA stop must not wedge the shutdown listener."""
    coordinator = entry.runtime_data
    original = kettle_client.write_gatt_char

    async def hanging_poll_write(characteristic, packet, response):
        if packet[6:10] == bytes.fromhex("00404000"):
            await asyncio.Future()
        await original(characteristic, packet, response)

    kettle_client.write_gatt_char = hanging_poll_write
    refresh = asyncio.create_task(coordinator.async_refresh())
    await asyncio.sleep(0.05)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert coordinator._shutdown_requested is True
    assert kettle_client.disconnect.await_count >= 1
    assert coordinator.device.is_connected is False
    await asyncio.gather(refresh, return_exceptions=True)


async def test_ha_shutdown_during_subscription_releases_ble(hass, entry, kettle_client):
    """A reconnect wedged in start_notify holds the connection lock.

    Shutdown must cancel the poll instead of waiting for its deadline:
    with a 20 ms disconnect-lock budget and a 350 ms poll deadline, the
    old code held BLE connected for the full 350 ms.
    """
    coordinator = entry.runtime_data
    started = asyncio.Event()

    async def hanging_subscription(*args, **kwargs):
        started.set()
        await asyncio.Future()

    kettle_client.start_notify.side_effect = hanging_subscription
    coordinator.device._handle_disconnect(coordinator.device._client)
    with (
        patch(
            "custom_components.cosori_kettle.cosori_kettle_ble.device"
            ".DISCONNECT_LOCK_TIMEOUT",
            0.02,
        ),
        patch("custom_components.cosori_kettle.coordinator.POLL_TIMEOUT", 0.35),
    ):
        refresh = asyncio.create_task(coordinator.async_refresh())
        await started.wait()
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        # Well under the 350 ms poll deadline: shutdown cancels the poll.
        await asyncio.wait_for(hass.async_block_till_done(), 0.15)
    assert coordinator._shutdown_requested is True
    assert kettle_client.disconnect.await_count >= 1
    assert coordinator.device.is_connected is False
    await asyncio.gather(refresh, return_exceptions=True)


async def test_ha_shutdown_during_active_command_releases_ble(
    hass, entry, kettle_client
):
    """A command in flight at HA stop is cancelled; BLE is released."""
    coordinator = entry.runtime_data
    original = kettle_client.write_gatt_char

    async def hanging_control_write(characteristic, packet, response):
        if packet[6:10] == bytes.fromhex("00f0a300"):
            await asyncio.Future()
        await original(characteristic, packet, response)

    kettle_client.write_gatt_char = hanging_control_write
    command = asyncio.create_task(coordinator.async_start_heating())
    await asyncio.sleep(0.05)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert command.cancelled()
    assert kettle_client.disconnect.await_count >= 1
    assert coordinator.device.is_connected is False


async def test_repeated_poll_failures_back_off(hass, entry):
    """Consecutive failures grow retry_after; success resets the cadence."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coordinator = entry.runtime_data
    with patch.object(
        coordinator.device, "update", side_effect=CosoriKettleTimeoutError("gone")
    ):
        for expected in (2, 4, 6):
            with pytest.raises(UpdateFailed) as raised:
                await coordinator._async_update_data()
            assert raised.value.retry_after == expected
    with patch.object(coordinator.device, "update"):
        await coordinator._async_update_data()
    with patch.object(
        coordinator.device, "update", side_effect=CosoriKettleTimeoutError("gone")
    ):
        with pytest.raises(UpdateFailed) as raised:
            await coordinator._async_update_data()
    assert raised.value.retry_after == 2


async def test_successful_command_resets_failure_backoff(hass, entry, kettle_client):
    """A successful command resets the poll-failure backoff cadence."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coordinator = entry.runtime_data
    with patch.object(
        coordinator.device, "update", side_effect=CosoriKettleTimeoutError("gone")
    ):
        with pytest.raises(UpdateFailed) as raised:
            await coordinator._async_update_data()
        assert raised.value.retry_after == 2
    await coordinator.async_start_heating()
    with patch.object(
        coordinator.device, "update", side_effect=CosoriKettleTimeoutError("gone")
    ):
        with pytest.raises(UpdateFailed) as raised:
            await coordinator._async_update_data()
        assert raised.value.retry_after == 2


async def test_temperature_only_request_recovers_availability_and_backoff(
    hass, entry, kettle_client
):
    """A staged target after failed polls restores availability and cadence.

    HA filters service calls to unavailable entities, so the regression
    drives the completed coordinator refresh and the command seam directly.
    """
    from datetime import timedelta

    from homeassistant.helpers.update_coordinator import UpdateFailed
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    coordinator = entry.runtime_data
    # Two completed refresh failures grow the backoff past the 2 s interval
    # and leave core's finally-block backoff timer installed.
    with patch.object(
        coordinator.device, "update", side_effect=CosoriKettleTimeoutError("gone")
    ):
        for expected in (2, 4):
            await coordinator.async_refresh()
            assert isinstance(coordinator.last_exception, UpdateFailed)
            assert coordinator.last_exception.retry_after == expected
    await hass.async_block_till_done()
    assert coordinator.last_update_success is False
    assert (
        hass.states.get("sensor.cosori_kettle_current_temperature").state
        == STATE_UNAVAILABLE
    )

    # Real device seam: staging polls fresh status without heating.
    await coordinator.async_set_temperature(80)
    await hass.async_block_till_done()

    assert coordinator.last_update_success is True
    assert (
        hass.states.get("sensor.cosori_kettle_current_temperature").state
        != STATE_UNAVAILABLE
    )
    assert hass.states.get("water_heater.cosori_kettle").attributes[
        "requested_temperature"
    ] == pytest.approx(80)
    assert kettle_client.target == 212  # staged only; physical setpoint untouched

    # Cadence: the next poll fires at the 2 s interval, not the 4 s backoff.
    kettle_client.writes.clear()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()
    assert [packet[6:10].hex() for packet in kettle_client.writes] == ["00404000"]

    # After recovery the next failure restarts the backoff at 2 s.
    with patch.object(
        coordinator.device, "update", side_effect=CosoriKettleTimeoutError("gone")
    ):
        await coordinator.async_refresh()
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.last_exception.retry_after == 2


async def test_reconnect_resolves_new_proxy_route(
    hass, entry, kettle_client, ble_device
):
    from bleak.backends.device import BLEDevice
    from conftest import KettleClient

    coordinator = entry.runtime_data
    fresh_device = BLEDevice(ble_device.address, ble_device.name, {"source": "proxy2"})
    fresh_client = KettleClient()
    coordinator.device._handle_disconnect(coordinator.device._client)
    with (
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=fresh_device,
        ),
        patch(
            f"{BLE_MODULE}.establish_connection", AsyncMock(return_value=fresh_client)
        ) as connect,
    ):
        await coordinator.async_refresh()
        assert coordinator.last_update_success is True
        assert connect.call_args.args[1] is fresh_device
        assert connect.call_args.kwargs["ble_device_callback"]() is fresh_device
        await coordinator.device.disconnect()
    kettle_client.disconnect.assert_awaited_once()
    fresh_client.disconnect.assert_awaited_once()


async def test_invalid_device_status_cannot_create_entry(
    hass, ble_device, kettle_client
):
    from custom_components.cosori_kettle.cosori_kettle_ble.device import (
        CosoriKettleDevice,
    )

    original_wait = CosoriKettleDevice._wait_status

    async def short_wait(self, require_base: bool = False):
        await original_wait(self, require_base, timeout=0.01)

    kettle_client.respond = False
    kettle_client.respond_poll = False
    with (
        patch(
            "homeassistant.components.bluetooth.async_discovered_service_info",
            return_value=[],
        ),
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=ble_device,
        ),
        patch(
            f"{BLE_MODULE}.establish_connection", AsyncMock(return_value=kettle_client)
        ),
        patch.object(CosoriKettleDevice, "_wait_status", short_wait),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ble_device.address}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_status"}
    assert hass.config_entries.async_entries(DOMAIN) == []
    kettle_client.disconnect.assert_awaited_once()


async def test_probe_deadline_binds_a_hanging_subscription(
    hass, ble_device, kettle_client, monkeypatch
):
    """A wedged start_notify must hit the probe deadline, not the dialog."""
    from custom_components.cosori_kettle import config_flow

    async def hang_notify(*args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(config_flow, "PROBE_TIMEOUT", 0.05)
    kettle_client.start_notify = hang_notify
    with (
        patch(
            "homeassistant.components.bluetooth.async_discovered_service_info",
            return_value=[],
        ),
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=ble_device,
        ),
        patch(
            f"{BLE_MODULE}.establish_connection", AsyncMock(return_value=kettle_client)
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ble_device.address}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert hass.config_entries.async_entries(DOMAIN) == []
    kettle_client.disconnect.assert_awaited_once()


async def test_probe_deadline_binds_a_hanging_status_read(
    hass, ble_device, kettle_client, monkeypatch
):
    """A wedged post-registration status read must hit the probe deadline."""
    from custom_components.cosori_kettle import config_flow
    from custom_components.cosori_kettle.cosori_kettle_ble.device import (
        CosoriKettleDevice,
    )

    async def hang_wait(self, *args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(config_flow, "PROBE_TIMEOUT", 1.0)
    with (
        patch(
            "homeassistant.components.bluetooth.async_discovered_service_info",
            return_value=[],
        ),
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=ble_device,
        ),
        patch(
            f"{BLE_MODULE}.establish_connection", AsyncMock(return_value=kettle_client)
        ),
        patch.object(CosoriKettleDevice, "_wait_status", hang_wait),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ble_device.address}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_status"}
    assert hass.config_entries.async_entries(DOMAIN) == []
    kettle_client.disconnect.assert_awaited_once()


async def test_manual_address_without_ha_route_reports_reachability(
    hass, ble_device, caplog
):
    with (
        patch(
            "homeassistant.components.bluetooth.async_discovered_service_info",
            return_value=[],
        ),
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=None,
        ),
        patch(
            "homeassistant.components.bluetooth.async_address_reachability_diagnostics",
            return_value="No scanner has received an advertisement for this address",
        ),
        patch(f"{BLE_MODULE}.establish_connection", AsyncMock()) as connect,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ble_device.address}
        )
    assert result["errors"] == {"base": "not_reachable"}
    assert "No scanner has received an advertisement" in caplog.text
    connect.assert_not_awaited()


async def test_setup_logs_connection_failure_reason(hass, ble_device, caplog):
    with (
        patch(
            "homeassistant.components.bluetooth.async_discovered_service_info",
            return_value=[],
        ),
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=ble_device,
        ),
        patch(
            f"{BLE_MODULE}.establish_connection",
            AsyncMock(side_effect=BleakError("proxy connection slot unavailable")),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ble_device.address}
        )
    assert result["errors"] == {"base": "cannot_connect"}
    assert "proxy connection slot unavailable" in caplog.text


async def test_water_heater_target_follows_kettle_setpoint(hass, entry, kettle_client):
    """The reported setpoint must track the kettle, not the first frame read."""
    kettle_client.target = 185
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("water_heater.cosori_kettle").attributes[
        "temperature"
    ] == pytest.approx(85, abs=0.5)


async def test_requested_temperature_follows_display_units(hass, entry, kettle_client):
    """The pending attribute renders in the configured unit system."""
    from homeassistant.util import unit_system

    hass.config.units = unit_system.IMPERIAL_SYSTEM
    await hass.services.async_call(
        "water_heater",
        "set_temperature",
        {"entity_id": "water_heater.cosori_kettle", "temperature": 176},
        blocking=True,
    )
    await hass.async_block_till_done()
    heater = hass.states.get("water_heater.cosori_kettle")
    assert heater.attributes["temperature"] == pytest.approx(212)
    assert heater.attributes["requested_temperature"] == pytest.approx(176)


async def test_poll_deadline_fails_and_recovers(hass, entry):
    """A stuck reconnection must fail within the deadline and not strand locks."""
    from conftest import KettleClient

    coordinator = entry.runtime_data
    coordinator.device._handle_disconnect(coordinator.device._client)

    async def hanging_connection(*args, **kwargs):
        await asyncio.Future()

    with (
        patch("custom_components.cosori_kettle.coordinator.POLL_TIMEOUT", 0.05),
        patch(f"{BLE_MODULE}.establish_connection", hanging_connection),
    ):
        await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success is False
    assert (
        hass.states.get("sensor.cosori_kettle_current_temperature").state
        == STATE_UNAVAILABLE
    )

    recovered = KettleClient()
    with patch(f"{BLE_MODULE}.establish_connection", AsyncMock(return_value=recovered)):
        await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success is True
    assert (
        hass.states.get("sensor.cosori_kettle_current_temperature").state
        != STATE_UNAVAILABLE
    )


async def test_command_deadline_reports_unconfirmed(hass, entry):
    """A control transaction that never finishes must surface as unconfirmed."""
    coordinator = entry.runtime_data

    async def hanging_start():
        await asyncio.Future()

    with (
        patch("custom_components.cosori_kettle.coordinator.COMMAND_TIMEOUT", 0.05),
        patch.object(coordinator.device, "start_heating", hanging_start),
    ):
        with pytest.raises(HomeAssistantError, match="unconfirmed"):
            await coordinator.async_start_heating()
    assert coordinator.last_update_success is False


async def test_unconfirmed_command_surfaces_as_home_assistant_error(hass, entry):
    from custom_components.cosori_kettle.cosori_kettle_ble.exceptions import (
        CosoriKettleUnconfirmedError,
    )

    coordinator = entry.runtime_data
    with patch.object(
        coordinator.device,
        "start_heating",
        side_effect=CosoriKettleUnconfirmedError("start written but unconfirmed"),
    ):
        with pytest.raises(HomeAssistantError, match="unconfirmed"):
            await coordinator.async_start_heating()
    assert coordinator.last_update_success is False


async def test_poll_deadline_releases_the_wedged_connection(hass, entry, kettle_client):
    """A timed-out write must force the next poll onto a fresh proxy route."""
    from conftest import KettleClient

    coordinator = entry.runtime_data
    original = kettle_client.write_gatt_char

    async def hanging_poll_write(characteristic, packet, response):
        if packet[6:10] == bytes.fromhex("00404000"):
            await asyncio.Future()
        await original(characteristic, packet, response)

    kettle_client.write_gatt_char = hanging_poll_write
    with patch("custom_components.cosori_kettle.coordinator.POLL_TIMEOUT", 0.05):
        await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success is False
    assert kettle_client.disconnect.await_count == 1
    assert coordinator.device.is_connected is False

    recovered = KettleClient()
    with patch(
        f"{BLE_MODULE}.establish_connection", AsyncMock(return_value=recovered)
    ) as connect:
        await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert connect.await_count == 1
    assert coordinator.last_update_success is True


async def test_command_deadline_releases_the_wedged_connection(
    hass, entry, kettle_client
):
    """A timed-out control write must not leave the client marked usable."""
    coordinator = entry.runtime_data
    original = kettle_client.write_gatt_char

    async def hanging_control_write(characteristic, packet, response):
        if packet[6:10] == bytes.fromhex("00f0a300"):
            await asyncio.Future()
        await original(characteristic, packet, response)

    kettle_client.write_gatt_char = hanging_control_write
    with patch("custom_components.cosori_kettle.coordinator.COMMAND_TIMEOUT", 0.5):
        with pytest.raises(HomeAssistantError, match="unconfirmed"):
            await coordinator.async_start_heating()
    assert kettle_client.disconnect.await_count == 1
    assert coordinator.device.is_connected is False


async def test_water_heater_stays_available_off_base_and_stops(
    hass, entry, kettle_client
):
    """Availability follows the link, so turn_off is never silently dropped."""
    coordinator = entry.runtime_data
    kettle_client.heating = True
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("water_heater.cosori_kettle").state == "on"

    kettle_client.on_base = False
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    heater = hass.states.get("water_heater.cosori_kettle")
    assert heater.state == "on"
    assert hass.states.get("binary_sensor.cosori_kettle_on_base").state == "off"

    await hass.services.async_call(
        "water_heater",
        "turn_off",
        {"entity_id": heater.entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert kettle_client.heating is False
    assert hass.states.get("water_heater.cosori_kettle").state == "off"


async def test_starting_heat_off_base_is_refused(hass, entry, kettle_client):
    """The base interlock guards starting heat, not the ability to stop it."""
    coordinator = entry.runtime_data
    kettle_client.on_base = False
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("water_heater.cosori_kettle").state == "off"
    with pytest.raises(ServiceValidationError, match="on its base"):
        await coordinator.async_start_heating()
    assert kettle_client.heating is False


async def test_flow_rejects_handshake_that_could_start_heating(
    hass, ble_device, kettle_client
):
    """A captured control frame must never become a replayed registration."""
    from custom_components.cosori_kettle.cosori_kettle_ble.protocol import (
        CosoriProtocol,
    )

    stream = b"".join(CosoriProtocol.build_hello_min()) + CosoriProtocol().build_ctrl()
    result = await _configure_manual_flow(
        hass,
        ble_device,
        {
            "handshake_1": stream[:14].hex(),
            "handshake_2": stream[14:28].hex(),
            "handshake_3": stream[28:].hex(),
        },
        connect=AsyncMock(),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_handshake"}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_flow_accepts_and_stores_a_valid_custom_handshake(
    hass, ble_device, kettle_client
):
    """The default registration is fragmented, so it must stay acceptable."""
    from custom_components.cosori_kettle.cosori_kettle_ble.protocol import (
        CosoriProtocol,
    )

    packets = CosoriProtocol.build_hello_min()
    result = await _configure_manual_flow(
        hass,
        ble_device,
        {f"handshake_{i + 1}": packet.hex() for i, packet in enumerate(packets)},
        connect=AsyncMock(return_value=kettle_client),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HANDSHAKE] == [packet.hex() for packet in packets]


@pytest.mark.parametrize(
    "stored_handshake", [["zz", "zz", "zz"], 42, [None], [42], "a522"]
)
async def test_invalid_stored_handshake_fails_setup_cleanly(
    hass, ble_device, caplog, stored_handshake
):
    """A corrupted or hand-edited entry must fail with a reason, not a crash."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Cosori Kettle",
        unique_id=ble_device.address,
        data={CONF_ADDRESS: ble_device.address, CONF_HANDSHAKE: stored_handshake},
    )
    entry.add_to_hass(hass)
    with (
        patch("homeassistant.setup.async_process_deps_reqs", AsyncMock()),
        patch("homeassistant.config_entries.async_process_deps_reqs", AsyncMock()),
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=ble_device,
        ),
        patch(f"{BLE_MODULE}.establish_connection", AsyncMock()) as connect,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert connect.await_count == 0
    assert "handshake" in caplog.text


def _discovery_info(ble_device, connectable=True):
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

    return BluetoothServiceInfoBleak(
        name="Cosori Kettle",
        address=ble_device.address,
        rssi=-60,
        manufacturer_data={},
        service_data={},
        service_uuids=[SERVICE_UUID],
        source="local",
        device=ble_device,
        advertisement=None,
        connectable=connectable,
        time=0.0,
        tx_power=None,
    )


async def test_bluetooth_discovery_confirm_creates_entry(
    hass, ble_device, kettle_client
):
    """The advertised path: discovery, confirm form, validated entry."""
    with (
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=ble_device,
        ),
        patch(
            f"{BLE_MODULE}.establish_connection", AsyncMock(return_value=kettle_client)
        ),
        patch(
            "custom_components.cosori_kettle.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "bluetooth"},
            data=_discovery_info(ble_device),
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "bluetooth_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ADDRESS: ble_device.address}
    assert result["context"]["unique_id"] == ble_device.address
    kettle_client.disconnect.assert_awaited_once()
    assert kettle_client.heating is False


async def test_bluetooth_discovery_aborts(hass, ble_device):
    """Non-connectable devices and already-configured kettles abort."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "bluetooth"},
        data=_discovery_info(ble_device, connectable=False),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"

    MockConfigEntry(
        domain=DOMAIN,
        unique_id=ble_device.address,
        data={CONF_ADDRESS: ble_device.address},
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "bluetooth"},
        data=_discovery_info(ble_device),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def _configure_manual_flow(hass, ble_device, user_input, connect):
    with (
        patch(
            "homeassistant.components.bluetooth.async_discovered_service_info",
            return_value=[],
        ),
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=ble_device,
        ),
        patch(f"{BLE_MODULE}.establish_connection", connect),
        patch(
            "custom_components.cosori_kettle.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        return await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ble_device.address, **user_input}
        )
