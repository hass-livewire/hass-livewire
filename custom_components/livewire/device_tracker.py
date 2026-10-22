"""Location of the bikes"""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LivewireConfigEntry
from .entity import LivewireEntity, LivewireEntityDescription, entities_to_add

LOCATION = LivewireEntityDescription(
    key="location",
    translation_key="location",
    exists_fn=lambda d: d.location is not None,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LivewireConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        entities_to_add(
            entry.runtime_data, Platform.DEVICE_TRACKER, (LOCATION,), LivewireTracker
        )
    )


class LivewireTracker(LivewireEntity, TrackerEntity):
    _attr_source_type = SourceType.GPS

    @property
    def latitude(self) -> float | None:
        location = self.bike_data.location
        return location.latitude if location else None

    @property
    def longitude(self) -> float | None:
        location = self.bike_data.location
        return location.longitude if location else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        location = self.bike_data.location
        if location is None:
            return None

        return {
            "altitude": location.altitude,
            "speed": location.speed_kmh,
            "gps_time": location.gps_time,
            "fix_type": location.fix_type,
        }
