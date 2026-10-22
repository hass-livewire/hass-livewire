"""Binary sensors of the LiveWire integration"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BikeData, LivewireConfigEntry
from .entity import LivewireEntity, LivewireEntityDescription, entities_to_add


@dataclass(frozen=True, kw_only=True)
class LivewireBinarySensorEntityDescription(
    LivewireEntityDescription, BinarySensorEntityDescription
):
    is_on_fn: Callable[[BikeData], bool | None]


BINARY_SENSORS: tuple[LivewireBinarySensorEntityDescription, ...] = (
    LivewireBinarySensorEntityDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        is_on_fn=lambda d: d.charging.charging if d.charging else None,
        exists_fn=lambda d: d.charging is not None,
    ),
    LivewireBinarySensorEntityDescription(
        key="plugged_in",
        translation_key="plugged_in",
        device_class=BinarySensorDeviceClass.PLUG,
        is_on_fn=lambda d: d.charging.plugged_in if d.charging else None,
        exists_fn=lambda d: d.charging is not None,
    ),
    LivewireBinarySensorEntityDescription(
        key="tire_pressure_front_low",
        translation_key="tire_pressure_front_low",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda d: d.tires.front_low if d.tires else None,
        exists_fn=lambda d: d.tires is not None,
    ),
    LivewireBinarySensorEntityDescription(
        key="tire_pressure_rear_low",
        translation_key="tire_pressure_rear_low",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda d: d.tires.rear_low if d.tires else None,
        exists_fn=lambda d: d.tires is not None,
    ),
    LivewireBinarySensorEntityDescription(
        key="paired",
        translation_key="paired",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: d.bike.paired,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LivewireConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        entities_to_add(
            entry.runtime_data,
            Platform.BINARY_SENSOR,
            BINARY_SENSORS,
            LivewireBinarySensor,
        )
    )


class LivewireBinarySensor(LivewireEntity, BinarySensorEntity):
    entity_description: LivewireBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.bike_data)
