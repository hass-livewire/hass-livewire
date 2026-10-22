"""Enhanced vehicle tracking of the bikes"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LivewireConfigEntry
from .entity import LivewireEntity, LivewireEntityDescription, entities_to_add

# It marks the bike as stolen, so it has to be enabled deliberately
ENHANCED_TRACKING = LivewireEntityDescription(
    key="enhanced_tracking",
    translation_key="enhanced_tracking",
    entity_registry_enabled_default=False,
    exists_fn=lambda d: d.charging is not None,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LivewireConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if not coordinator.add_command_entities:
        return

    async_add_entities(
        entities_to_add(
            coordinator,
            Platform.SWITCH,
            (ENHANCED_TRACKING,),
            LivewireEnhancedTracking,
        )
    )


class LivewireEnhancedTracking(LivewireEntity, SwitchEntity):
    """Reports the bike as stolen, it then sends its position every few minutes"""

    @property
    def is_on(self) -> bool | None:
        charging = self.bike_data.charging
        status = (charging.tracking_status or "").upper() if charging else ""

        # PENDING while the bike has not confirmed a change yet
        return {"STOLEN": True, "SAFE": False}.get(status)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_enhanced_tracking(self.bike_data.bike.id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_enhanced_tracking(
            self.bike_data.bike.id, False
        )
