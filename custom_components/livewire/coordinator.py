"""Coordinator for the LiveWire integration"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterable
import dataclasses
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from py_livewire import (
    AuthenticationError,
    Bike,
    ChargingSchedule,
    ChargingStatus,
    Client,
    LivewireError,
    Location,
    NotPairedError,
    SoftwareVersion,
    TirePressure,
)

from .const import (
    CONF_ADD_COMMAND_ENTITIES,
    CONF_CHARGING_SCAN_INTERVAL,
    CONF_DEVICE_UUID,
    CONF_PAIRING_SKIPPED,
    DEFAULT_ADD_COMMAND_ENTITIES,
    DEFAULT_CHARGING_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EXTRA_DATA_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type LivewireConfigEntry = ConfigEntry[LivewireCoordinator]

# Errors of requests that failed: py-livewire passes those of aiohttp through
REQUEST_ERRORS = (LivewireError, aiohttp.ClientError, TimeoutError)


@dataclass
class BikeData:
    """A bike and the latest data fetched for it"""

    bike: Bike
    charging: ChargingStatus | None = None
    location: Location | None = None
    tires: TirePressure | None = None
    software: SoftwareVersion | None = None
    schedules: list[ChargingSchedule] | None = None

    @property
    def vin(self) -> str:
        """The key of the bike, its VIN, or its id if it has none"""
        return self.bike.vin or self.bike.id

    @property
    def name(self) -> str:
        return self.bike.name or self.bike.model or self.vin


def not_paired_issue_id(bike: Bike) -> str:
    return f"not_paired_{bike.id}"


def utc_offset_minutes() -> int:
    """The current UTC offset of Home Assistant's time zone, for schedules"""
    offset = dt_util.now().utcoffset()
    return int(offset.total_seconds() // 60) if offset else 0


def any_charging(items: Iterable[BikeData]) -> bool:
    return any(item.charging is not None and item.charging.charging for item in items)


class LivewireCoordinator(DataUpdateCoordinator[dict[str, BikeData]]):
    """Fetches the data of all bikes of an account"""

    config_entry: LivewireConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: LivewireConfigEntry) -> None:
        self.client = Client(
            email=config_entry.data[CONF_USERNAME],
            password=config_entry.data[CONF_PASSWORD],
            device_uuid=config_entry.data[CONF_DEVICE_UUID],
            session=async_get_clientsession(hass),
        )

        # Entities are created by the setup, a change of this option reloads
        self.add_command_entities: bool = config_entry.options.get(
            CONF_ADD_COMMAND_ENTITIES, DEFAULT_ADD_COMMAND_ENTITIES
        )
        self._extra_data_updated: datetime | None = None

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=self._read_interval(config_entry, charging=False),
            always_update=True,
        )

    @staticmethod
    def _read_interval(config_entry: ConfigEntry, *, charging: bool) -> timedelta:
        """Return the polling interval, a shorter one while a bike is charging"""

        options = config_entry.options
        if charging:
            minutes = options.get(
                CONF_CHARGING_SCAN_INTERVAL, DEFAULT_CHARGING_SCAN_INTERVAL
            )
        else:
            minutes = options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

        return timedelta(minutes=minutes)

    async def _async_update_data(self) -> dict[str, BikeData]:
        previous = self.data or {}

        try:
            bikes = await self.client.get_bikes()
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except REQUEST_ERRORS as err:
            if not previous:
                raise UpdateFailed(f"Fetching the bikes failed: {err}") from err
            _LOGGER.warning("Update failed, keeping the last data: %s", err)
            return previous

        data: dict[str, BikeData] = {}
        for bike in bikes:
            item = BikeData(bike=bike)
            if (old := previous.get(item.vin)) is not None:
                item = dataclasses.replace(old, bike=bike)
            data[item.vin] = item

        await asyncio.gather(*(self._async_update_bike(item) for item in data.values()))
        await self._async_update_extra_data(data)
        self._update_issues(data.values())

        self.update_interval = self._read_interval(
            self.config_entry, charging=any_charging(data.values())
        )

        return data

    async def _fetch[T](
        self, what: str, item: BikeData, call: Awaitable[T]
    ) -> T | None:
        """Await a request for a bike, None if it failed"""

        try:
            return await call
        except NotPairedError as err:
            # The bike did not answer, the pairing is checked separately
            _LOGGER.debug("%s of %s not available: %s", what, item.name, err)
        except REQUEST_ERRORS as err:
            _LOGGER.warning("Fetching the %s of %s failed: %s", what, item.name, err)
        return None

    async def _async_update_bike(self, item: BikeData) -> None:
        """Fetch the data that changes often, keeping the previous on failures"""

        bike = item.bike

        # Only a paired device UUID gets the charging status
        if bike.paired:
            charging = await self._fetch(
                "charging status", item, self.client.get_charging_status(bike.id)
            )
            if charging is not None:
                item.charging = charging
        else:
            item.charging = None

        location = await self._fetch(
            "location", item, self.client.get_location(bike.id)
        )
        if location is not None:
            item.location = location

    async def _async_update_extra_data(self, data: dict[str, BikeData]) -> None:
        """Fetch the data that rarely changes, at most every EXTRA_DATA_INTERVAL"""

        now = dt_util.utcnow()
        if (
            self._extra_data_updated is not None
            and now - self._extra_data_updated < EXTRA_DATA_INTERVAL
        ):
            return
        self._extra_data_updated = now

        async def update(item: BikeData) -> None:
            bike = item.bike

            tires = await self._fetch(
                "tire pressure",
                item,
                self.client.get_tire_pressure(bike.id, bike.model_code),
            )
            if tires is not None:
                item.tires = tires

            schedules = await self._fetch(
                "charging schedules", item, self.client.get_charging_schedules(bike.id)
            )
            if schedules is not None:
                item.schedules = schedules

        try:
            versions = await self.client.get_software_versions()
        except REQUEST_ERRORS as err:
            _LOGGER.warning("Fetching the software versions failed: %s", err)
            versions = []

        by_bike_id = {version.bike_id: version for version in versions}
        for item in data.values():
            if (version := by_bike_id.get(item.bike.id)) is not None:
                item.software = version

        await asyncio.gather(*(update(item) for item in data.values()))

    @callback
    def _update_issues(self, items: Iterable[BikeData]) -> None:
        """Raise a repair issue for each bike the device UUID is not paired with.

        Not if the user chose to continue without pairing.
        """

        skipped = self.config_entry.data.get(CONF_PAIRING_SKIPPED, False)

        for item in items:
            issue_id = not_paired_issue_id(item.bike)
            if item.bike.paired is False and not skipped:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="not_paired",
                    translation_placeholders={"bike": item.name},
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    @callback
    def async_delete_issues(self) -> None:
        for item in (self.data or {}).values():
            ir.async_delete_issue(self.hass, DOMAIN, not_paired_issue_id(item.bike))

    async def async_update_options(
        self, hass: HomeAssistant, config_entry: LivewireConfigEntry
    ) -> None:
        """Apply changed options, reloading if entities are to be added or removed"""

        add_command_entities = config_entry.options.get(
            CONF_ADD_COMMAND_ENTITIES, DEFAULT_ADD_COMMAND_ENTITIES
        )
        if add_command_entities != self.add_command_entities:
            hass.config_entries.async_schedule_reload(config_entry.entry_id)
            return

        self.update_interval = self._read_interval(
            config_entry, charging=any_charging((self.data or {}).values())
        )

    async def _async_call[T](self, call: Awaitable[T], translation_key: str) -> T:
        """Await a library call, reporting its errors as Home Assistant errors"""

        try:
            return await call
        except NotPairedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_reachable",
                translation_placeholders={"error": str(err)},
            ) from err
        except REQUEST_ERRORS as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=translation_key,
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_set_charge_limit(self, bike_id: str, limit: int) -> None:
        await self._async_call(
            self.client.set_charge_limit(bike_id, limit), "set_charge_limit_failed"
        )
        await self.async_request_refresh()

    async def async_start_charging(self, bike_id: str) -> None:
        await self._async_call(
            self.client.start_charging(bike_id), "start_charging_failed"
        )
        await self.async_request_refresh()

    async def async_set_enhanced_tracking(self, bike_id: str, enabled: bool) -> None:
        await self._async_call(
            self.client.set_enhanced_tracking(bike_id, enabled), "set_tracking_failed"
        )
        await self.async_request_refresh()

    async def _async_refresh_schedules(self, item: BikeData) -> None:
        """Fetch the changed charging schedules of a bike right away"""

        item.schedules = await self._async_call(
            self.client.get_charging_schedules(item.bike.id), "schedule_failed"
        )
        self.async_update_listeners()

    async def async_add_charging_schedule(
        self, item: BikeData, days: list[str], start: time, end: time
    ) -> None:
        await self._async_call(
            self.client.add_charging_schedule(
                item.bike.id, days, start, end, utc_offset_minutes=utc_offset_minutes()
            ),
            "schedule_failed",
        )
        await self._async_refresh_schedules(item)

    async def async_update_charging_schedule(
        self, item: BikeData, schedule_id: str, days: list[str], start: time, end: time
    ) -> None:
        await self._async_call(
            self.client.update_charging_schedule(
                item.bike.id,
                schedule_id,
                days,
                start,
                end,
                utc_offset_minutes=utc_offset_minutes(),
            ),
            "schedule_failed",
        )
        await self._async_refresh_schedules(item)

    async def async_delete_charging_schedule(
        self, item: BikeData, schedule_id: str
    ) -> None:
        await self._async_call(
            self.client.delete_charging_schedule(item.bike.id, schedule_id),
            "schedule_failed",
        )
        await self._async_refresh_schedules(item)
