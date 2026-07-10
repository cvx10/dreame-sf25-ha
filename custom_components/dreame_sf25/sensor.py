"""Sensor platform for Dreame SF25 Food Composter."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVITY_STATES,
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
    PROP_ENERGY,
    PROP_HUMIDITY,
    PROP_TEMPERATURE,
    PROP_TIME_REMAINING,
    RUN_FLAG_CODES,
    STATUS_CODES,
    activity_state,
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
        # 3/14 was long believed to be a temperature, but a full-cycle history
        # showed it is a cumulative counter: resets to 0 at cycle start, ramps
        # fast during heat-up, then climbs monotonically (~1/min) without ever
        # plateauing — consistent with heater energy in Wh, not °C.
        key=PROP_ENERGY,
        name="Energy",
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SF25SensorDescription(
        # 3/2 — chamber humidity. A full drying cycle (2026-07-10) settled the
        # label: ~57 at rest (indoor RH), spikes ~71 when the wet load heats up,
        # then declines to ~34 as it dries, and drifts back up after the cycle.
        # A temperature cannot follow that shape; relative humidity does.
        key=PROP_HUMIDITY,
        name="Humidity",
        icon="mdi:water-percent",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SF25SensorDescription(
        # 3/3 — chamber temperature, confirmed by the same cycle: ~30 °C idle
        # (ambient), ramps to ~141 within 10 min of start, plateaus at 142-143
        # for the whole drying phase, falls to ~37 by the end of cooling.
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
# A derived timestamp sensor: when the running cycle is expected to finish.
FINISH_KEY = "estimated_finish"
# A derived enum sensor unifying status + run_flag + mode into one clear state.
ACTIVITY_KEY = "activity"

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
    entities.append(DreameSF25ActivitySensor(coordinator, entry.entry_id))
    entities.append(DreameSF25FinishSensor(coordinator, entry.entry_id))
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

    @property
    def available(self) -> bool:
        # While the MQTT link is down we cannot trust any value: report
        # 'unavailable' rather than showing a stale state as if it were live.
        return self.coordinator.mqtt_connected


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


class DreameSF25ActivitySensor(_BaseSF25Sensor):
    """Unified activity state combining status, run flag and mode.

    The raw device splits its state across three properties: 2/1 (status, which
    is 2 for idle/paused/stopped alike), 2/10 (run_flag, the real run-state
    discriminator) and 2/3 (mode). This sensor folds them into one readable
    state so a dashboard does not have to reconcile three entities.
    """

    _attr_name = "Activity"
    _attr_icon = "mdi:leaf"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ACTIVITY_STATES

    def __init__(self, coordinator: DreameSF25Coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, ACTIVITY_KEY)

    def _fresh_native_value(self) -> Any:
        data = self.coordinator.data or {}
        if PROP_RUN_FLAG not in data:
            return _MISSING
        return activity_state(data.get(PROP_RUN_FLAG), data.get(PROP_MODE))


class DreameSF25FinishSensor(_BaseSF25Sensor):
    """Estimated finish time (timestamp) derived from the remaining minutes.

    Only meaningful while a cycle is actively running. The value is recomputed
    only when the remaining time changes, so it stays stable between the
    once-a-minute countdown ticks instead of drifting on every read.
    """

    _attr_name = "Estimated Finish"
    _attr_icon = "mdi:clock-end"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: DreameSF25Coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, FINISH_KEY)
        self._last_remaining: int | None = None
        self._finish_at: datetime | None = None

    def _fresh_native_value(self) -> Any:
        data = self.coordinator.data or {}
        if PROP_TIME_REMAINING not in data:
            return _MISSING
        remaining = data[PROP_TIME_REMAINING]
        # Only show a finish time while a cycle is actually running. The run
        # flag (2/10) is only pushed on transitions, so after a mid-cycle HA
        # restart it is absent until the next start/pause/stop: treat absent
        # as running instead of hiding the finish time for the rest of the
        # cycle.
        if PROP_RUN_FLAG in data and data[PROP_RUN_FLAG] != 1:
            self._last_remaining = None
            self._finish_at = None
            return None
        if not remaining or remaining <= 0:
            self._last_remaining = None
            self._finish_at = None
            return None
        candidate = dt_util.utcnow() + timedelta(minutes=remaining)
        # Recompute when the countdown ticks, but also re-anchor when the
        # device holds the countdown (adaptive drying pauses 2/11 while
        # humidity is high): a frozen remaining would otherwise let the
        # stored finish drift into the past. 5 min of skew keeps the value
        # stable across normal once-a-minute ticks.
        if (
            remaining != self._last_remaining
            or self._finish_at is None
            or abs((candidate - self._finish_at).total_seconds()) > 300
        ):
            self._last_remaining = remaining
            self._finish_at = candidate
        return self._finish_at
