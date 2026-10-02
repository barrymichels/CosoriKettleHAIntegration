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
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CosoriKettleConfigEntry, kettle_device_info
from .coordinator import CosoriKettleDataUpdateCoordinator
from .cosori_kettle_ble.const import MAX_TEMP_C, MIN_TEMP_C

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CosoriKettleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
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
    _attr_min_temp = MIN_TEMP_C
    _attr_max_temp = MAX_TEMP_C
    _attr_operation_list = [STATE_OFF, STATE_ON]
    # The kettle accepts whole Fahrenheit setpoints; 5/9 °C is exactly 1 °F.
    _attr_target_temperature_step = 5 / 9

    def __init__(
        self,
        coordinator: CosoriKettleDataUpdateCoordinator,
        entry: CosoriKettleConfigEntry,
    ) -> None:
        """Initialize the water heater."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_water_heater"
        self._attr_device_info = kettle_device_info(entry, coordinator.device.address)

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
        """Return the heating state; the base interlock guards starting heat."""
        return STATE_ON if self.coordinator.heating else STATE_OFF

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        _LOGGER.debug("Setting target temperature to %.1f°C", temperature)
        mode = kwargs.get(ATTR_OPERATION_MODE)
        if mode is not None and mode not in (self.operation_list or []):
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
        """Start heating with the target already staged or reported."""
        _LOGGER.debug("Turning on heating")
        await self.coordinator.async_start_heating()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off heating."""
        _LOGGER.debug("Turning off heating")
        await self.coordinator.async_stop_heating()
