"""Sensor platform for Cosori Kettle integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CosoriKettleConfigEntry
from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import CosoriKettleDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CosoriKettleSensorEntityDescription(SensorEntityDescription):
    """Describes Cosori Kettle sensor entity."""

    value_fn: Callable[[CosoriKettleDataUpdateCoordinator], float | None] | None = None


SENSORS: tuple[CosoriKettleSensorEntityDescription, ...] = (
    CosoriKettleSensorEntityDescription(
        key="current_temperature",
        name="Current Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda coordinator: coordinator.current_temp_c,
        entity_registry_enabled_default=True,
    ),
    CosoriKettleSensorEntityDescription(
        key="target_temperature",
        entity_category=EntityCategory.DIAGNOSTIC,
        name="Target Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda coordinator: coordinator.target_temp_c,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CosoriKettleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Cosori Kettle sensors from a config entry."""
    coordinator: CosoriKettleDataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        CosoriKettleSensor(coordinator, entry, description) for description in SENSORS
    )


class CosoriKettleSensor(
    CoordinatorEntity[CosoriKettleDataUpdateCoordinator], SensorEntity
):
    """Representation of a Cosori Kettle sensor."""

    _attr_has_entity_name = True
    entity_description: CosoriKettleSensorEntityDescription

    def __init__(
        self,
        coordinator: CosoriKettleDataUpdateCoordinator,
        entry: CosoriKettleConfigEntry,
        description: CosoriKettleSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "connections": {(CONNECTION_BLUETOOTH, coordinator.device.address)},
            "name": entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(self.coordinator)
