"""Charge limit of the bikes"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CHARGE_LIMIT_MAX, CHARGE_LIMIT_MIN, CHARGE_LIMIT_STEP
from .coordinator import LivewireConfigEntry
from .entity import LivewireEntity, LivewireEntityDescription, entities_to_add


@dataclass(frozen=True, kw_only=True)
class LivewireNumberEntityDescription(
    LivewireEntityDescription, NumberEntityDescription
):
    """Description of a number entity of a bike"""


CHARGE_LIMIT = LivewireNumberEntityDescription(
    key="charge_limit_setting",
    translation_key="charge_limit_setting",
    native_min_value=CHARGE_LIMIT_MIN,
    native_max_value=CHARGE_LIMIT_MAX,
    native_step=CHARGE_LIMIT_STEP,
    native_unit_of_measurement=PERCENTAGE,
    mode=NumberMode.SLIDER,
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
            coordinator, Platform.NUMBER, (CHARGE_LIMIT,), LivewireChargeLimit
        )
    )


class LivewireChargeLimit(LivewireEntity, NumberEntity):
    @property
    def native_value(self) -> float | None:
        charging = self.bike_data.charging
        return charging.charge_limit if charging else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_charge_limit(
            self.bike_data.bike.id, int(value)
        )
