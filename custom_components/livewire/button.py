"""Buttons of the LiveWire integration"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LivewireConfigEntry
from .entity import LivewireEntity, LivewireEntityDescription, entities_to_add

START_CHARGING = LivewireEntityDescription(
    key="start_charging",
    translation_key="start_charging",
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
            coordinator, Platform.BUTTON, (START_CHARGING,), LivewireStartCharging
        )
    )


class LivewireStartCharging(LivewireEntity, ButtonEntity):
    """Starts charging right away instead of waiting for a charging schedule"""

    async def async_press(self) -> None:
        await self.coordinator.async_start_charging(self.bike_data.bike.id)
