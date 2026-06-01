"""Sensor platform for Dreame SF25 Food Composter."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    FULL_CYCLE_MINUTES,
    MANUFACTURER,
    MODEL,
    MODE_CODES,
    MODE_DURATIONS,
    PROP_MODE,
    PROP_PROGRAM,
    PROP_RUN_FLAG,
    PROP_STATUS,
    PROP_TEMPERATURE,
    PROP_TIME_REMAINING,
    RUN_FLAG_CODES,
    STATUS_CODES,
)
from .coordinator import DreameSF25Coordinator


@dataclass(frozen=True, kw_only=True)
class SF25SensorDescription(SensorEntityDescription):
    """Sensor description with an optional value transformer."""

    value_fn: Callable[[Any], Any] | None = None


def _map_or_raw(mapping: dict) -> Callable[[Any], Any]:
    return lambda v: mapping.get(v, f"unknown_{v}") if v is not None else None


SENSOR_DESCRIPTIONS: tuple[SF25SensorDescription, ...] = (
    SF25SensorDescription(
        key=PROP_STATUS,
        name="Status",
        icon="mdi:state-machine",
        device_class=SensorDeviceClass.ENUM,
        options=list(STATUS_CODES.values()),
        value_fn=_map_or_raw(STATUS_CODES),
    ),
    SF25SensorDescription(
        key=PROP_RUN_FLAG,
        name="Run State",
        icon="mdi:play-pause",
        device_class=SensorDeviceClass.ENUM,
        options=list(RUN_FLAG_CODES.values()),
        value_fn=_map_or_raw(RUN_FLAG_CODES),
    ),
    SF25SensorDescription(
        key=PROP_MODE,
        name="Mode",
        icon="mdi:leaf",
        device_class=SensorDeviceClass.ENUM,
        options=list(MODE_CODES.values()),
        value_fn=lambda v: MODE_CODES.get(v) if v is not None else None,
    ),
    SF25SensorDescription(
        key=PROP_PROGRAM,
        name="Program",
        icon="mdi:tune-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        # 1/6 is a raw program/recipe code (e.g. "m01"); meaning of the suffix
        # is not yet confirmed, so expose it verbatim.
        value_fn=lambda v: v,
    ),
    SF25SensorDescription(
        key=PROP_TIME_REMAINING,
        name="Time Remaining",
        icon="mdi:timer-sand",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SF25SensorDescription(
        key=PROP_TEMPERATURE,
        name="Temperature",
        icon="mdi:thermometer",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

# A derived progress sensor (0–100%) computed from the remaining time.
PROGRESS_KEY = "progress"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameSF25Coordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        DreameSF25Sensor(coordinator, description, entry.entry_id)
        for description in SENSOR_DESCRIPTIONS
    ]
    entities.append(DreameSF25ProgressSensor(coordinator, entry.entry_id))
    async_add_entities(entities)


class _BaseSF25Sensor(CoordinatorEntity[DreameSF25Coordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DreameSF25Coordinator, entry_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator._did)},
            "name": coordinator.device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "model_id": coordinator.model_id,
        }


class DreameSF25Sensor(_BaseSF25Sensor):
    """A sensor mapped directly to a single MQTT property."""

    entity_description: SF25SensorDescription

    def __init__(
        self,
        coordinator: DreameSF25Coordinator,
        description: SF25SensorDescription,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        raw = (self.coordinator.data or {}).get(self.entity_description.key)
        if self.entity_description.value_fn:
            return self.entity_description.value_fn(raw)
        return raw


class DreameSF25ProgressSensor(_BaseSF25Sensor):
    """Derived cycle-progress sensor (0–100%) from remaining time."""

    _attr_name = "Cycle Progress"
    _attr_icon = "mdi:progress-clock"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DreameSF25Coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, PROGRESS_KEY)

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data or {}
        remaining = data.get(PROP_TIME_REMAINING)
        if remaining is None or remaining <= 0:
            return None
        # Pick the full duration for the current operation (drying=360, cleaning=90),
        # falling back to the default. This keeps progress accurate per mode.
        total = MODE_DURATIONS.get(data.get(PROP_MODE), FULL_CYCLE_MINUTES)
        remaining = max(0, min(total, remaining))
        return round((total - remaining) / total * 100)
