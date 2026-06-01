"""Sensor platform for Dreame SF25 Food Composter."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    RestoreSensor,
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


def _map_enum(mapping: dict) -> Callable[[Any], Any]:
    """Map a coded value to its name for an ENUM sensor.

    Unknown/unmapped codes return None (HA state 'unknown') rather than a
    synthetic string: an ENUM sensor raises if its state is not in `options`,
    which would crash the coordinator's listener update. The raw code is still
    visible in debug logs and (for 1/6) via the Program sensor.
    """
    return lambda v: mapping.get(v) if v is not None else None


SENSOR_DESCRIPTIONS: tuple[SF25SensorDescription, ...] = (
    SF25SensorDescription(
        key=PROP_STATUS,
        name="Status",
        icon="mdi:state-machine",
        device_class=SensorDeviceClass.ENUM,
        options=list(STATUS_CODES.values()),
        value_fn=_map_enum(STATUS_CODES),
    ),
    SF25SensorDescription(
        key=PROP_RUN_FLAG,
        name="Run State",
        icon="mdi:play-pause",
        device_class=SensorDeviceClass.ENUM,
        options=list(RUN_FLAG_CODES.values()),
        value_fn=_map_enum(RUN_FLAG_CODES),
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

# Sentinel: the coordinator has not yet received this property (vs. a real None).
_MISSING = object()


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


class _BaseSF25Sensor(CoordinatorEntity[DreameSF25Coordinator], RestoreSensor):
    """Base sensor that restores its last value across restarts.

    The SF25 only pushes state (no polled read), so after a restart the
    coordinator has no data until the device next pushes. RestoreSensor lets us
    show the last known value in the meantime instead of 'unknown'. As soon as
    the relevant property is pushed, the live value takes over.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: DreameSF25Coordinator, entry_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_{key}"
        self._restored_native_value: Any = None
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator._did)},
            "name": coordinator.device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "model_id": coordinator.model_id,
        }

    async def async_added_to_hass(self) -> None:
        # super() chains through CoordinatorEntity (registers the push listener)
        # and RestoreEntity (loads stored state).
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None:
            self._restored_native_value = last.native_value

    def _fresh_native_value(self) -> Any:
        """Return the live value, or _MISSING if not yet pushed. Subclasses override."""
        return _MISSING

    @property
    def native_value(self) -> Any:
        value = self._fresh_native_value()
        # Fall back to the restored value only while the property is absent.
        return self._restored_native_value if value is _MISSING else value


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

    def _fresh_native_value(self) -> Any:
        data = self.coordinator.data or {}
        key = self.entity_description.key
        if key not in data:
            return _MISSING
        raw = data[key]
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

    def _fresh_native_value(self) -> int | None | object:
        data = self.coordinator.data or {}
        if PROP_TIME_REMAINING not in data:
            return _MISSING
        remaining = data[PROP_TIME_REMAINING]
        if remaining is None or remaining <= 0:
            return None  # no active cycle (property present but zero)
        # Pick the full duration for the current operation (drying=360, cleaning=90),
        # falling back to the default. This keeps progress accurate per mode.
        total = MODE_DURATIONS.get(data.get(PROP_MODE), FULL_CYCLE_MINUTES)
        remaining = max(0, min(total, remaining))
        return round((total - remaining) / total * 100)
