"""Binary sensor platform for Dreame SF25 Food Composter."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    MODEL,
    PROP_LID,
    PROP_LID_ALERT,
)
from .coordinator import DreameSF25Coordinator


@dataclass(frozen=True, kw_only=True)
class SF25BinaryDescription(BinarySensorEntityDescription):
    """Binary sensor description with an is-on transformer."""

    is_on_fn: Callable[[Any], bool | None]


BINARY_DESCRIPTIONS: tuple[SF25BinaryDescription, ...] = (
    SF25BinaryDescription(
        key=PROP_LID,
        name="Lid",
        device_class=BinarySensorDeviceClass.OPENING,
        icon="mdi:window-shutter-open",
        # 6/11: 1 = open, 0 = closed
        is_on_fn=lambda v: bool(v) if v is not None else None,
    ),
    SF25BinaryDescription(
        key=PROP_LID_ALERT,
        name="Lid Alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:alert",
        # 2/2: 1 = lid-open alert, 0 = ok
        is_on_fn=lambda v: bool(v) if v is not None else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameSF25Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DreameSF25BinarySensor(coordinator, description, entry.entry_id)
        for description in BINARY_DESCRIPTIONS
    )


class DreameSF25BinarySensor(
    CoordinatorEntity[DreameSF25Coordinator], BinarySensorEntity
):
    _attr_has_entity_name = True
    entity_description: SF25BinaryDescription

    def __init__(
        self,
        coordinator: DreameSF25Coordinator,
        description: SF25BinaryDescription,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator._did)},
            "name": coordinator.device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "model_id": coordinator.model_id,
        }

    @property
    def is_on(self) -> bool | None:
        raw = (self.coordinator.data or {}).get(self.entity_description.key)
        return self.entity_description.is_on_fn(raw)
