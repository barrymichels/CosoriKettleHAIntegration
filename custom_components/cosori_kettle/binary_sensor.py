"""Binary sensor platform for Cosori Kettle integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CosoriKettleConfigEntry
from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import CosoriKettleDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CosoriKettleBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes Cosori Kettle binary sensor entity."""

    value_fn: Callable[[CosoriKettleDataUpdateCoordinator], bool | None] | None = None


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
    async_add_entities: AddEntitiesCallback,
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
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "connections": {(CONNECTION_BLUETOOTH, coordinator.device.address)},
            "name": entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    @property
    def is_on(self) -> bool | None:
        """Return the state of the binary sensor."""
        if self.entity_description.value_fn is None:
            return False
        return self.entity_description.value_fn(self.coordinator)
