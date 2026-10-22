"""Base entity for the LiveWire integration"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BikeData, LivewireCoordinator


@dataclass(frozen=True, kw_only=True)
class LivewireEntityDescription(EntityDescription):
    """Description of an entity created for the bikes that provide its data"""

    exists_fn: Callable[[BikeData], bool] = lambda _: True


def unique_id(vin: str, key: str) -> str:
    return f"{DOMAIN}_{vin}_{key}"


def should_add(hass: HomeAssistant, platform: str, uid: str, supported: bool) -> bool:
    """Return whether to create an entity.

    It is created if the bike provides its data, or if it was created before: data
    missing at startup (a request failing, the bike being unreachable) must not make
    an existing entity disappear.
    """

    if supported:
        return True

    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, uid) is not None


def entities_to_add[D: LivewireEntityDescription, E](
    coordinator: LivewireCoordinator,
    platform: str,
    descriptions: tuple[D, ...],
    entity_cls: Callable[[LivewireCoordinator, BikeData, D], E],
) -> list[E]:
    """Create the entities of the descriptions for all bikes that provide them"""

    return [
        entity_cls(coordinator, item, description)
        for item in coordinator.data.values()
        for description in descriptions
        if should_add(
            coordinator.hass,
            platform,
            unique_id(item.vin, description.key),
            description.exists_fn(item),
        )
    ]


class LivewireEntity(CoordinatorEntity[LivewireCoordinator]):
    """An entity of a bike"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: LivewireCoordinator,
        item: BikeData,
        description: EntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._vin = item.vin
        self._last_data = item
        self._attr_unique_id = unique_id(item.vin, description.key)

        bike = item.bike
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, item.vin)},
            manufacturer=bike.make or "LiveWire",
            model=bike.model,
            model_id=bike.model_code,
            name=item.name,
            serial_number=bike.vin,
            sw_version=item.software.current if item.software else None,
        )

    @property
    def bike_data(self) -> BikeData:
        """The current data of the bike.

        If the bike was removed from the account, the last data is returned and the
        entity is unavailable.
        """

        if (item := self.coordinator.data.get(self._vin)) is not None:
            self._last_data = item
        return self._last_data

    @property
    def available(self) -> bool:
        return super().available and self._vin in self.coordinator.data
