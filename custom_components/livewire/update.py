"""Vehicle software versions of the bikes"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import REQUEST_ERRORS, LivewireConfigEntry
from .entity import LivewireEntity, LivewireEntityDescription, entities_to_add


@dataclass(frozen=True, kw_only=True)
class LivewireUpdateEntityDescription(
    LivewireEntityDescription, UpdateEntityDescription
):
    """Description of an update entity of a bike"""


SOFTWARE = LivewireUpdateEntityDescription(
    key="software",
    translation_key="software",
    device_class=UpdateDeviceClass.FIRMWARE,
    exists_fn=lambda d: d.software is not None,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LivewireConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        entities_to_add(
            entry.runtime_data, Platform.UPDATE, (SOFTWARE,), LivewireSoftwareUpdate
        )
    )


class LivewireSoftwareUpdate(LivewireEntity, UpdateEntity):
    """The bike installs new software over the air, this only reports it"""

    _attr_supported_features = UpdateEntityFeature.RELEASE_NOTES

    @property
    def installed_version(self) -> str | None:
        software = self.bike_data.software
        return software.current if software else None

    @property
    def latest_version(self) -> str | None:
        software = self.bike_data.software
        if software is None:
            return None
        return software.latest or software.current

    async def async_release_notes(self) -> str | None:
        latest = self.latest_version
        if latest is None:
            return None

        try:
            notes = await self.coordinator.client.get_software_release_notes(
                self.bike_data.bike.id, [latest]
            )
        except REQUEST_ERRORS:
            return None

        return "\n\n".join(
            note["vsbReleaseNote"] for note in notes if note.get("vsbReleaseNote")
        )
