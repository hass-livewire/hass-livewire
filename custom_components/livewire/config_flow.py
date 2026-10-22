"""Config flow for the LiveWire integration.

After logging in, the user either enters a device UUID that is already paired with
the motorcycle (e.g. the one of the phone app), or pairs one: the bike shows a code on
its display, which the user enters here. Reconfiguring the entry offers the same
choice, pairing then uses the entry's device UUID so that other bikes stay paired.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from typing import Any
import uuid

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_CODE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from py_livewire import AuthenticationError, Bike, Client, PairingError
import voluptuous as vol

from .const import (
    CONF_ADD_COMMAND_ENTITIES,
    CONF_CHARGING_SCAN_INTERVAL,
    CONF_DEVICE_UUID,
    CONF_PAIRING_SKIPPED,
    DEFAULT_ADD_COMMAND_ENTITIES,
    DEFAULT_CHARGING_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PAIRING_POLL_INTERVAL,
    PAIRING_TIMEOUT,
)
from .coordinator import REQUEST_ERRORS

_LOGGER = logging.getLogger(__name__)

CONF_BIKE = "bike"

CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)

DEVICE_UUID_SCHEMA = vol.Schema({vol.Required(CONF_DEVICE_UUID): str})

CODE_SCHEMA = vol.Schema({vol.Required(CONF_CODE): str})

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=1440)
        ),
        vol.Required(
            CONF_CHARGING_SCAN_INTERVAL, default=DEFAULT_CHARGING_SCAN_INTERVAL
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
        vol.Required(
            CONF_ADD_COMMAND_ENTITIES, default=DEFAULT_ADD_COMMAND_ENTITIES
        ): bool,
    }
)

DEFAULT_OPTIONS = {
    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
    CONF_CHARGING_SCAN_INTERVAL: DEFAULT_CHARGING_SCAN_INTERVAL,
    CONF_ADD_COMMAND_ENTITIES: DEFAULT_ADD_COMMAND_ENTITIES,
}

# PairingError codes when requesting or verifying a pairing code
PAIRING_ERRORS = {
    400: "bike_not_ready",
    402: "no_cellular",
    4003: "attempts_exceeded",
    4004: "wrong_code",
}


def error_key(err: Exception) -> str:
    """Return the form error for an exception of a request"""

    if isinstance(err, AuthenticationError):
        return "invalid_auth"
    if isinstance(err, REQUEST_ERRORS):
        _LOGGER.warning("Request failed: %s", err)
        return "cannot_connect"

    _LOGGER.exception("Unexpected exception")
    return "unknown"


def bike_label(bike: Bike) -> str:
    return " ".join(str(x) for x in (bike.year, bike.model, bike.name) if x)


class LivewireOptionsFlow(OptionsFlow):
    """Options of a LiveWire entry"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )


class LivewireConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow of LiveWire"""

    VERSION = 1

    def __init__(self) -> None:
        self._username: str = ""
        self._password: str = ""
        self._bikes: list[Bike] = []
        self._device_uuid: str | None = None
        self._pairing_skipped = False

        # Pairing state
        self._pairing_client: Client | None = None
        self._bike: Bike | None = None
        self._pair_task: asyncio.Task[bool] | None = None
        self._pair_errors: dict[str, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> LivewireOptionsFlow:
        return LivewireOptionsFlow()

    def _client(self, device_uuid: str | None = None) -> Client:
        return Client(
            email=self._username,
            password=self._password,
            device_uuid=device_uuid,
            session=async_get_clientsession(self.hass),
        )

    async def _async_login(self, user_input: Mapping[str, Any]) -> Client:
        """Log in with the given credentials and fetch the bikes"""

        self._username = user_input[CONF_USERNAME].strip()
        self._password = user_input[CONF_PASSWORD]

        client = self._client()
        self._bikes = await client.get_bikes()
        return client

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the credentials of the LiveWire account"""

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                client = await self._async_login(user_input)
            except Exception as err:
                errors["base"] = error_key(err)
            else:
                if not self._bikes:
                    return self.async_abort(reason="no_bikes")

                await self.async_set_unique_id(client.user_id)
                self._abort_if_unique_id_configured()
                return await self.async_step_device()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                CREDENTIALS_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose between an already paired device UUID and pairing one"""

        return self.async_show_menu(
            step_id="device", menu_options=["device_uuid", "pair", "skip"]
        )

    async def async_step_device_uuid(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Use a device UUID that is paired with at least one of the bikes"""

        errors: dict[str, str] = {}

        if user_input is not None:
            device_uuid = user_input[CONF_DEVICE_UUID].strip()

            try:
                uuid.UUID(device_uuid)
            except ValueError:
                errors[CONF_DEVICE_UUID] = "invalid_uuid"
            else:
                try:
                    bikes = await self._client(device_uuid).get_bikes()
                except Exception as err:
                    errors["base"] = error_key(err)
                else:
                    if any(bike.paired for bike in bikes):
                        self._device_uuid = device_uuid
                        return await self.async_step_finish()
                    errors[CONF_DEVICE_UUID] = "not_paired"

        return self.async_show_form(
            step_id="device_uuid",
            data_schema=self.add_suggested_values_to_schema(
                DEVICE_UUID_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start pairing: a new device UUID, or the one of the reconfigured entry"""

        if self.source == SOURCE_RECONFIGURE:
            self._device_uuid = self._get_reconfigure_entry().data[CONF_DEVICE_UUID]
        else:
            self._device_uuid = str(uuid.uuid4())

        self._pairing_client = self._client(self._device_uuid)

        # The pairing status of the bikes for this device UUID
        try:
            self._bikes = await self._pairing_client.get_bikes()
        except Exception as err:
            return self.async_abort(reason=error_key(err))

        if not self._bikes:
            return self.async_abort(reason="no_bikes")
        if len(self._bikes) == 1:
            self._bike = self._bikes[0]
            return await self.async_step_pair_start()

        return await self.async_step_pick_bike()

    async def async_step_pick_bike(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the bike to pair with"""

        if user_input is not None:
            self._bike = next(b for b in self._bikes if b.id == user_input[CONF_BIKE])
            return await self.async_step_pair_start()

        options = [
            SelectOptionDict(value=bike.id, label=bike_label(bike))
            for bike in self._bikes
        ]
        return self.async_show_form(
            step_id="pick_bike",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BIKE): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    def _placeholders(self) -> dict[str, str]:
        assert self._bike is not None
        return {"bike": bike_label(self._bike)}

    async def async_step_pair_start(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain how to prepare the bike, then make it show a pairing code"""

        assert self._bike is not None and self._pairing_client is not None

        # Nothing to do if the device UUID is already paired with the bike
        if self._bike.paired:
            return await self.async_step_finish()

        # Errors of later steps that lead back here, shown until a new attempt.
        # The form can be shown twice, the flow advances by itself after a
        # progress step.
        errors = dict(self._pair_errors)

        if user_input is not None:
            errors, self._pair_errors = {}, {}
            try:
                await self._pairing_client.request_pairing_code(self._bike.id)
            except PairingError as err:
                _LOGGER.warning("Requesting a pairing code failed: %s", err)
                errors["base"] = PAIRING_ERRORS.get(err.code or 0, "pairing_failed")
            except Exception as err:
                errors["base"] = error_key(err)
            else:
                return await self.async_step_pair_code()

        return self.async_show_form(
            step_id="pair_start",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    async def async_step_pair_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the code the bike shows on its display"""

        assert self._bike is not None and self._pairing_client is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await self._pairing_client.verify_pairing_code(
                    self._bike.id, user_input[CONF_CODE].strip()
                )
            except PairingError as err:
                _LOGGER.warning("Verifying the pairing code failed: %s", err)
                reason = PAIRING_ERRORS.get(err.code or 0, "pairing_failed")
                if reason != "wrong_code":
                    # The code is used up, a new one has to be requested
                    self._pair_errors = {"base": reason}
                    return await self.async_step_pair_start()
                errors["base"] = reason
            except Exception as err:
                errors["base"] = error_key(err)
            else:
                return await self.async_step_pair_wait()

        return self.async_show_form(
            step_id="pair_code",
            data_schema=CODE_SCHEMA,
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    async def _async_wait_paired(self) -> bool:
        """Poll until the backend confirms the pairing, False after the timeout"""

        assert self._bike is not None and self._pairing_client is not None

        loop = asyncio.get_running_loop()
        deadline = loop.time() + PAIRING_TIMEOUT

        while True:
            try:
                if await self._pairing_client.is_paired(self._bike.id):
                    return True
            except REQUEST_ERRORS as err:
                _LOGGER.debug("Checking the pairing status failed: %s", err)

            if loop.time() >= deadline:
                return False
            await asyncio.sleep(PAIRING_POLL_INTERVAL)

    async def async_step_pair_wait(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wait for the bike to confirm the pairing"""

        if self._pair_task is None:
            # Not started eagerly, the progress is always shown first
            self._pair_task = self.hass.async_create_task(
                self._async_wait_paired(), eager_start=False
            )

        if not self._pair_task.done():
            return self.async_show_progress(
                step_id="pair_wait",
                progress_action="wait_for_pairing",
                progress_task=self._pair_task,
                description_placeholders=self._placeholders(),
            )

        task, self._pair_task = self._pair_task, None
        if not task.result():
            self._pair_errors = {"base": "not_confirmed"}
            return self.async_show_progress_done(next_step_id="pair_start")

        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_skip(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Continue without pairing: only the data that needs no pairing"""

        # A device UUID is needed for the session anyway, it can be paired later
        if self.source == SOURCE_RECONFIGURE:
            self._device_uuid = self._get_reconfigure_entry().data[CONF_DEVICE_UUID]
        else:
            self._device_uuid = str(uuid.uuid4())

        self._pairing_skipped = True
        return await self.async_step_finish()

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry, or update the reconfigured one"""

        assert self._device_uuid is not None

        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data_updates={
                    CONF_DEVICE_UUID: self._device_uuid,
                    CONF_PAIRING_SKIPPED: self._pairing_skipped,
                },
            )

        return self.async_create_entry(
            title=self._username,
            data={
                CONF_USERNAME: self._username,
                CONF_PASSWORD: self._password,
                CONF_DEVICE_UUID: self._device_uuid,
                CONF_PAIRING_SKIPPED: self._pairing_skipped,
            },
            options=DEFAULT_OPTIONS,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Ask for new credentials when they were rejected"""

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                client = await self._async_login(user_input)
            except Exception as err:
                errors["base"] = error_key(err)
            else:
                await self.async_set_unique_id(client.user_id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    title=self._username,
                    data_updates={
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                CREDENTIALS_SCHEMA,
                user_input or {CONF_USERNAME: entry.data[CONF_USERNAME]},
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the device UUID or pair it with a bike"""

        entry = self._get_reconfigure_entry()

        try:
            await self._async_login(entry.data)
        except Exception as err:
            return self.async_abort(reason=error_key(err))

        return await self.async_step_device()
