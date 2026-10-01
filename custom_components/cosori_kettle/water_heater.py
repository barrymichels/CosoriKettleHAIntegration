"""Water heater platform for Cosori Kettle integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.water_heater import (
    ATTR_OPERATION_MODE,
    STATE_OFF,
    STATE_ON,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CosoriKettleConfigEntry
from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import CosoriKettleDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CosoriKettleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Cosori Kettle water heater from a config entry."""
    coordinator: CosoriKettleDataUpdateCoordinator = entry.runtime_data
    async_add_entities([CosoriKettleWaterHeater(coordinator, entry)])


class CosoriKettleWaterHeater(
    CoordinatorEntity[CosoriKettleDataUpdateCoordinator], WaterHeaterEntity
):
    """Representation of Cosori Kettle as a water heater entity."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.ON_OFF
        | WaterHeaterEntityFeature.OPERATION_MODE
    )
    _attr_min_temp = 40
    _attr_max_temp = 100
    _attr_operation_list = [STATE_OFF, STATE_ON]
    _attr_target_temperature_step = 5 / 9

    def __init__(
        self,
        coordinator: CosoriKettleDataUpdateCoordinator,
        entry: CosoriKettleConfigEntry,
    ) -> None:
        """Initialize the water heater."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_water_heater"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "connections": {(CONNECTION_BLUETOOTH, coordinator.device.address)},
            "name": entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    @property
    def current_temperature(self) -> float | None:
        """Return current water temperature."""
        return self.coordinator.current_temp_c

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""
        return self.coordinator.target_temp_c

    @property
    def current_operation(self) -> str:
        """Return current operation (off/on)."""
        if not self.coordinator.on_base:
            return STATE_OFF
        if self.coordinator.heating:
            return STATE_ON
        return STATE_OFF

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        _LOGGER.debug("Setting target temperature to %.1f°C", temperature)
        mode = kwargs.get(ATTR_OPERATION_MODE)
        if mode is not None and mode not in self.operation_list:
            raise ServiceValidationError(f"Unsupported operation mode: {mode}")
        await self.coordinator.async_set_temperature(
            temperature, start=None if mode is None else mode == STATE_ON
        )

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set operation mode."""
        _LOGGER.debug("Setting operation mode to %s", operation_mode)
        if operation_mode == STATE_ON:
            await self.coordinator.async_start_heating()
        elif operation_mode == STATE_OFF:
            await self.coordinator.async_stop_heating()
        else:
            raise ServiceValidationError(
                f"Unsupported operation mode: {operation_mode}"
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on heating."""
        _LOGGER.debug("Turning on heating")
        # If temperature is provided, set it first
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.coordinator.async_set_temperature(temperature, start=True)
        else:
            await self.coordinator.async_start_heating()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off heating."""
        _LOGGER.debug("Turning off heating")
        await self.coordinator.async_stop_heating()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Entity is available if coordinator has data and device is on base
        return super().available and self.coordinator.on_base is True
