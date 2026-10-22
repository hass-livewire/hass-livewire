"""Services of the LiveWire integration: managing charging schedules"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
import voluptuous as vol

from .const import DOMAIN
from .coordinator import BikeData, LivewireCoordinator

SERVICE_ADD_CHARGING_SCHEDULE = "add_charging_schedule"
SERVICE_UPDATE_CHARGING_SCHEDULE = "update_charging_schedule"
SERVICE_DELETE_CHARGING_SCHEDULE = "delete_charging_schedule"

ATTR_DAYS = "days"
ATTR_START = "start"
ATTR_END = "end"
ATTR_SCHEDULE_ID = "schedule_id"

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_DAY_LIST = vol.All(cv.ensure_list, [vol.All(cv.string, vol.Lower, vol.In(DAYS))])

BASE_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): cv.string})

ADD_SCHEMA = BASE_SCHEMA.extend(
    {
        vol.Required(ATTR_DAYS): vol.All(_DAY_LIST, vol.Length(min=1)),
        vol.Required(ATTR_START): cv.time,
        vol.Required(ATTR_END): cv.time,
    }
)

# No days disable a schedule, as the app does it
UPDATE_SCHEMA = BASE_SCHEMA.extend(
    {
        vol.Required(ATTR_SCHEDULE_ID): cv.string,
        vol.Required(ATTR_DAYS): _DAY_LIST,
        vol.Required(ATTR_START): cv.time,
        vol.Required(ATTR_END): cv.time,
    }
)

DELETE_SCHEMA = BASE_SCHEMA.extend({vol.Required(ATTR_SCHEDULE_ID): cv.string})


@callback
def _resolve_bike(
    hass: HomeAssistant, call: ServiceCall
) -> tuple[LivewireCoordinator, BikeData]:
    """Return the coordinator and data of the bike the call targets"""

    device = dr.async_get(hass).async_get(call.data[ATTR_DEVICE_ID])
    vin = (
        next(
            (key for domain, key in device.identifiers if domain == DOMAIN),
            None,
        )
        if device
        else None
    )

    if device is None or vin is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_device"
        )

    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if (
            entry is not None
            and entry.domain == DOMAIN
            and entry.state is ConfigEntryState.LOADED
            and (item := entry.runtime_data.data.get(vin)) is not None
        ):
            return entry.runtime_data, item

    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="bike_not_loaded"
    )


def _check_schedule(item: BikeData, schedule_id: str) -> None:
    """Reject schedule ids the bike does not have, if its schedules are known"""

    if item.schedules is not None and schedule_id not in {
        schedule.id for schedule in item.schedules
    }:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_schedule",
            translation_placeholders={"schedule_id": schedule_id},
        )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services"""

    async def add_schedule(call: ServiceCall) -> None:
        coordinator, item = _resolve_bike(hass, call)
        await coordinator.async_add_charging_schedule(
            item, call.data[ATTR_DAYS], call.data[ATTR_START], call.data[ATTR_END]
        )

    async def update_schedule(call: ServiceCall) -> None:
        coordinator, item = _resolve_bike(hass, call)
        _check_schedule(item, call.data[ATTR_SCHEDULE_ID])
        await coordinator.async_update_charging_schedule(
            item,
            call.data[ATTR_SCHEDULE_ID],
            call.data[ATTR_DAYS],
            call.data[ATTR_START],
            call.data[ATTR_END],
        )

    async def delete_schedule(call: ServiceCall) -> None:
        coordinator, item = _resolve_bike(hass, call)
        _check_schedule(item, call.data[ATTR_SCHEDULE_ID])
        await coordinator.async_delete_charging_schedule(
            item, call.data[ATTR_SCHEDULE_ID]
        )

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_CHARGING_SCHEDULE, add_schedule, schema=ADD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_CHARGING_SCHEDULE, update_schedule, schema=UPDATE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_CHARGING_SCHEDULE, delete_schedule, schema=DELETE_SCHEMA
    )
