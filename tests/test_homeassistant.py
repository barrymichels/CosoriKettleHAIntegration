"""Use real HA setup, platforms, config flows, and service validation."""

import json
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

from custom_components.cosori_kettle.const import DOMAIN
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
    assert kettle_client.writes == []
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
    assert entry.runtime_data.target_temp_c == pytest.approx(90)


async def test_disconnect_staged_target_and_unload(hass, entry, kettle_client):
    coordinator = entry.runtime_data
    coordinator.device._handle_disconnect(coordinator.device._client)
    await hass.async_block_till_done()
    assert (
        hass.states.get("sensor.cosori_kettle_current_temperature").state
        == STATE_UNAVAILABLE
    )
    await coordinator.async_set_temperature(80)
    assert coordinator.last_update_success is False
    await hass.async_block_till_done()
    assert (
        hass.states.get("sensor.cosori_kettle_current_temperature").state
        == STATE_UNAVAILABLE
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert coordinator._shutdown_requested is True
    kettle_client.disconnect.assert_awaited_once()


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
    assert manifest["iot_class"] == "local_polling"
    assert set(manifest["requirements"]) <= set(core_manifest["requirements"])


async def test_ha_shutdown_releases_connection(hass, entry, kettle_client):
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert entry.runtime_data._shutdown_requested is True
    kettle_client.disconnect.assert_awaited_once()


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

    async def short_wait(self):
        await original_wait(self, 0.01)

    kettle_client.respond = False
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
