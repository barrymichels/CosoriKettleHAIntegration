"""Discover or select a kettle and validate its actual BLE protocol."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers import selector

from .const import CONF_HANDSHAKE, DOMAIN, SERVICE_UUID
from .cosori_kettle_ble import CosoriKettleDevice
from .cosori_kettle_ble.exceptions import CosoriKettleError

_LOGGER = logging.getLogger(__name__)

HANDSHAKE_FIELDS = ("handshake_1", "handshake_2", "handshake_3")
MAC_PATTERN = re.compile(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")


class CosoriKettleConfigFlow(ConfigFlow, domain=DOMAIN):
    """FFF0 is generic: only create entries after receiving kettle status."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        if not discovery_info.connectable:
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(discovery_info.address.upper())
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_bluetooth_confirm()

    def _handshake_schema(self) -> dict[Any, Any]:
        if not self.show_advanced_options:
            return {}
        return {vol.Optional(field): str for field in HANDSHAKE_FIELDS}

    async def _validate_device(
        self, address: str, user_input: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any]]:
        """Probe without heating; return (error key, entry data)."""
        try:
            values = [user_input.get(field, "").strip() for field in HANDSHAKE_FIELDS]
            handshake = (
                [bytes.fromhex(value.replace(":", "")) for value in values]
                if any(values)
                else None
            )
            if handshake is not None and any(not packet for packet in handshake):
                return "invalid_handshake", {}
        except ValueError:
            return "invalid_handshake", {}
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, address, connectable=True
        )
        if ble_device is None:
            details = bluetooth.async_address_reachability_diagnostics(
                self.hass, address, bluetooth.BluetoothReachabilityIntent.CONNECTION
            )
            _LOGGER.warning(
                "No Bluetooth connection route for %s: %s", address, details
            )
            return "not_reachable", {}
        device = CosoriKettleDevice(ble_device, handshake=handshake)
        registered = False
        try:
            await device.connect()
            registered = True
            await device.update()
        except CosoriKettleError as err:
            stage = "reading status" if registered else "connecting/registering"
            _LOGGER.warning(
                "Kettle setup failed for %s while %s: %s", address, stage, err
            )
            return "no_status" if registered else "cannot_connect", {}
        finally:
            await device.disconnect()
        entry_data: dict[str, Any] = {CONF_ADDRESS: address}
        if handshake is not None:
            entry_data[CONF_HANDSHAKE] = [packet.hex() for packet in handshake]
        return None, entry_data

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery_info is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            error, entry_data = await self._validate_device(
                self._discovery_info.address.upper(), user_input
            )
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=self._discovery_info.name or "Cosori Kettle",
                    data=entry_data,
                )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(self._handshake_schema()),
            errors=errors,
            description_placeholders={
                "name": self._discovery_info.name or "Cosori Kettle"
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            if not MAC_PATTERN.fullmatch(address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                error, entry_data = await self._validate_device(address, user_input)
                if error:
                    errors["base"] = error
                else:
                    info = self._discovered_devices.get(address)
                    return self.async_create_entry(
                        title=(info.name if info else None) or "Cosori Kettle",
                        data=entry_data,
                    )
        current_addresses = self._async_current_ids()
        self._discovered_devices = {
            info.address.upper(): info
            for info in bluetooth.async_discovered_service_info(
                self.hass, connectable=True
            )
            if info.address.upper() not in current_addresses
            and SERVICE_UUID in [uuid.lower() for uuid in info.service_uuids]
        }
        address_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=address,
                        label=f"{info.name or 'BLE device'} ({address})",
                    )
                    for address, info in self._discovered_devices.items()
                ],
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): address_selector,
                    **self._handshake_schema(),
                }
            ),
            errors=errors,
        )
