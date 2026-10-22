"""Sensors of the LiveWire integration"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    Platform,
    UnitOfLength,
    UnitOfPressure,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BikeData, LivewireConfigEntry
from .entity import LivewireEntity, LivewireEntityDescription, entities_to_add

# Units of tire pressures as the API names them, compared in lower case
PRESSURE_UNITS = {
    "psi": UnitOfPressure.PSI,
    "kpa": UnitOfPressure.KPA,
    "bar": UnitOfPressure.BAR,
}

TRACKING_STATES = ["safe", "stolen", "pending"]


@dataclass(frozen=True, kw_only=True)
class LivewireSensorEntityDescription(
    LivewireEntityDescription, SensorEntityDescription
):
    value_fn: Callable[[BikeData], Any]
    attributes_fn: Callable[[BikeData], dict[str, Any] | None] = lambda _: None


def _charging(get: Callable[[Any], Any]) -> Callable[[BikeData], Any]:
    """Read a value of the charging status"""
    return lambda d: get(d.charging) if d.charging is not None else None


def _has_charging(d: BikeData) -> bool:
    return d.charging is not None


def _tracking_status(d: BikeData) -> str | None:
    status = (d.charging.tracking_status or "").lower() if d.charging else ""
    return status if status in TRACKING_STATES else None


def _time_to_limit(d: BikeData) -> float | None:
    if d.charging is None or d.charging.time_to_limit is None:
        return None
    return d.charging.time_to_limit.total_seconds() / 60


def _tire_pressure_attributes(front: bool) -> Callable[[BikeData], dict[str, Any]]:
    def get(d: BikeData) -> dict[str, Any]:
        tires = d.tires
        if tires is None:
            return {}
        recommended = tires.front_recommended if front else tires.rear_recommended
        return {"recommended": recommended}

    return get


def _schedule_attributes(d: BikeData) -> dict[str, Any]:
    return {
        "schedules": [
            {
                "id": s.id,
                "status": s.status,
                "days": s.days,
                "start": s.start.strftime("%H:%M") if s.start else None,
                "end": s.end.strftime("%H:%M") if s.end else None,
            }
            for s in d.schedules or []
        ]
    }


SENSORS: tuple[LivewireSensorEntityDescription, ...] = (
    LivewireSensorEntityDescription(
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=_charging(lambda c: c.battery_level),
        exists_fn=_has_charging,
    ),
    LivewireSensorEntityDescription(
        key="range",
        translation_key="range",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.MILES,
        suggested_display_precision=0,
        value_fn=_charging(lambda c: c.range_miles),
        exists_fn=_has_charging,
    ),
    LivewireSensorEntityDescription(
        key="odometer",
        translation_key="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.MILES,
        suggested_display_precision=0,
        value_fn=_charging(lambda c: c.odometer_miles),
        exists_fn=_has_charging,
    ),
    LivewireSensorEntityDescription(
        key="charge_limit",
        translation_key="charge_limit",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_charging(lambda c: c.charge_limit),
        exists_fn=_has_charging,
    ),
    LivewireSensorEntityDescription(
        key="time_to_charge_limit",
        translation_key="time_to_charge_limit",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=_time_to_limit,
        exists_fn=_has_charging,
    ),
    LivewireSensorEntityDescription(
        key="tracking_status",
        translation_key="tracking_status",
        device_class=SensorDeviceClass.ENUM,
        options=TRACKING_STATES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_tracking_status,
        exists_fn=_has_charging,
    ),
    LivewireSensorEntityDescription(
        key="last_reported",
        translation_key="last_reported",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.location.reported_at if d.location else None,
        exists_fn=lambda d: d.location is not None,
    ),
    LivewireSensorEntityDescription(
        key="tire_pressure_front",
        translation_key="tire_pressure_front",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.tires.front if d.tires else None,
        attributes_fn=_tire_pressure_attributes(front=True),
        exists_fn=lambda d: d.tires is not None,
    ),
    LivewireSensorEntityDescription(
        key="tire_pressure_rear",
        translation_key="tire_pressure_rear",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.tires.rear if d.tires else None,
        attributes_fn=_tire_pressure_attributes(front=False),
        exists_fn=lambda d: d.tires is not None,
    ),
    LivewireSensorEntityDescription(
        key="charging_schedules",
        translation_key="charging_schedules",
        value_fn=lambda d: len(d.schedules) if d.schedules is not None else None,
        attributes_fn=_schedule_attributes,
        exists_fn=lambda d: d.schedules is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LivewireConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        entities_to_add(entry.runtime_data, Platform.SENSOR, SENSORS, LivewireSensor)
    )


class LivewireSensor(LivewireEntity, SensorEntity):
    entity_description: LivewireSensorEntityDescription

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.bike_data)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.device_class == SensorDeviceClass.PRESSURE:
            # The unit comes with the values, psi has been seen
            unit = self.bike_data.tires.unit if self.bike_data.tires else None
            return PRESSURE_UNITS.get((unit or "psi").lower())
        return super().native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attributes_fn(self.bike_data)
