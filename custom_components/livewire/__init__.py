"""The LiveWire integration"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import LivewireConfigEntry, LivewireCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the LiveWire integration"""

    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LivewireConfigEntry) -> bool:
    """Set up LiveWire from a config entry"""

    coordinator = LivewireCoordinator(hass, entry)

    # Raises ConfigEntryNotReady, or ConfigEntryAuthFailed to start reauth
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(coordinator.async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: LivewireConfigEntry) -> bool:
    """Unload a config entry"""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry.runtime_data.async_delete_issues()

    return unload_ok
