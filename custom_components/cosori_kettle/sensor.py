"""Sensor platform for Cosori Kettle integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Cosori Kettle sensors from a config entry."""
    coordinator: CosoriKettleDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
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
        entry: ConfigEntry,
        description: CosoriKettleSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "sw_version": "1.0",
        }

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(self.coordinator)
