"""Binary sensor platform for Cosori Kettle integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CosoriKettleConfigEntry, kettle_device_info
from .coordinator import CosoriKettleDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class CosoriKettleBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes Cosori Kettle binary sensor entity."""

    value_fn: Callable[[CosoriKettleDataUpdateCoordinator], bool | None]


BINARY_SENSORS: tuple[CosoriKettleBinarySensorEntityDescription, ...] = (
    CosoriKettleBinarySensorEntityDescription(
        key="on_base",
        name="On Base",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda coordinator: coordinator.on_base,
        entity_registry_enabled_default=True,
    ),
    CosoriKettleBinarySensorEntityDescription(
        key="heating",
        name="Heating",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda coordinator: coordinator.heating,
        entity_registry_enabled_default=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CosoriKettleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Cosori Kettle binary sensors from a config entry."""
    coordinator: CosoriKettleDataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        CosoriKettleBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSORS
    )


class CosoriKettleBinarySensor(
    CoordinatorEntity[CosoriKettleDataUpdateCoordinator], BinarySensorEntity
):
    """Representation of a Cosori Kettle binary sensor."""

    _attr_has_entity_name = True
    entity_description: CosoriKettleBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: CosoriKettleDataUpdateCoordinator,
        entry: CosoriKettleConfigEntry,
        description: CosoriKettleBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = kettle_device_info(entry, coordinator.device.address)

    @property
    def is_on(self) -> bool | None:
        """Return if the binary sensor is on."""
        return self.entity_description.value_fn(self.coordinator)
