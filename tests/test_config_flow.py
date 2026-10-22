"""Config, pairing, reauth, reconfigure and options flows"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch
import uuid

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    CONF_CODE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from py_livewire import AuthenticationError, LivewireError, PairingError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.livewire.const import (
    CONF_ADD_COMMAND_ENTITIES,
    CONF_CHARGING_SCAN_INTERVAL,
    CONF_DEVICE_UUID,
    CONF_PAIRING_SKIPPED,
    DOMAIN,
)

from .conftest import BIKE_ID, DEVICE_UUID, USER_ID, FakeClient

CREDENTIALS = {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}


@pytest.fixture(autouse=True)
def no_setup() -> Iterator[None]:
    """Created and updated entries are not set up"""

    with (
        patch("custom_components.livewire.async_setup_entry", return_value=True),
        patch("custom_components.livewire.async_unload_entry", return_value=True),
    ):
        yield


@pytest.fixture(autouse=True)
def fast_pairing() -> Iterator[None]:
    with patch("custom_components.livewire.config_flow.PAIRING_POLL_INTERVAL", 0):
        yield


async def start(hass: HomeAssistant) -> dict[str, Any]:
    """Log in and return the device menu"""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "device"
    return result


async def choose(hass: HomeAssistant, result: dict[str, Any], step: str) -> dict:
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def test_existing_device_uuid(
    hass: HomeAssistant, fake_client: FakeClient
) -> None:
    result = await choose(hass, await start(hass), "device_uuid")
    assert result["step_id"] == "device_uuid"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_UUID: f" {DEVICE_UUID} "}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "user@example.com"
    assert result["data"] == {
        **CREDENTIALS,
        CONF_DEVICE_UUID: DEVICE_UUID,
        CONF_PAIRING_SKIPPED: False,
    }
    assert result["options"] == {
        CONF_SCAN_INTERVAL: 5,
        CONF_CHARGING_SCAN_INTERVAL: 1,
        CONF_ADD_COMMAND_ENTITIES: True,
    }
    assert result["result"].unique_id == USER_ID
    assert fake_client.device_uuids[-1] == DEVICE_UUID


async def test_skip_pairing(hass: HomeAssistant, fake_client: FakeClient) -> None:
    result = await choose(hass, await start(hass), "skip")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_PAIRING_SKIPPED] is True
    assert uuid.UUID(data[CONF_DEVICE_UUID]).version == 4
    fake_client.request_pairing_code.assert_not_awaited()


async def test_existing_device_uuid_errors(
    hass: HomeAssistant, fake_client: FakeClient
) -> None:
    result = await choose(hass, await start(hass), "device_uuid")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_UUID: "not-a-uuid"}
    )
    assert result["errors"] == {CONF_DEVICE_UUID: "invalid_uuid"}

    fake_client.paired = set()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_UUID: DEVICE_UUID}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_DEVICE_UUID: "not_paired"}


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AuthenticationError("Invalid LoginID"), "invalid_auth"),
        (LivewireError("backend down"), "cannot_connect"),
        (aiohttp.ClientConnectionError("reset"), "cannot_connect"),
        (TimeoutError(), "cannot_connect"),
        (RuntimeError("bug"), "unknown"),
    ],
)
async def test_login_errors(
    hass: HomeAssistant, fake_client: FakeClient, error: Exception, reason: str
) -> None:
    fake_client.get_bikes.side_effect = error

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": reason}


async def test_no_bikes(hass: HomeAssistant, fake_client: FakeClient) -> None:
    fake_client.bikes = []

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_bikes"


async def test_already_configured(
    hass: HomeAssistant, fake_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def start_pairing(hass: HomeAssistant, fake_client: FakeClient) -> dict:
    """Go to the pairing instructions with a new device UUID"""

    fake_client.paired = set()

    result = await choose(hass, await start(hass), "pair")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair_start"
    assert result["description_placeholders"] == {
        "bike": "2025 S2 Mulholland Mulholland"
    }
    return result


async def test_pair(hass: HomeAssistant, fake_client: FakeClient) -> None:
    result = await start_pairing(hass, fake_client)

    # The pairing UUID is new
    pair_uuid = fake_client.device_uuids[-1]
    assert uuid.UUID(pair_uuid).version == 4
    assert pair_uuid != DEVICE_UUID

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pair_code"
    fake_client.request_pairing_code.assert_awaited_once_with(BIKE_ID)

    # The bike confirms the pairing on the second poll
    fake_client.is_paired.side_effect = [False, True]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: " 123456 "}
    )
    fake_client.verify_pairing_code.assert_awaited_once_with(BIKE_ID, "123456")
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "wait_for_pairing"

    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY

    [entry] = hass.config_entries.async_entries(DOMAIN)
    assert entry.data == {
        **CREDENTIALS,
        CONF_DEVICE_UUID: pair_uuid,
        CONF_PAIRING_SKIPPED: False,
    }
    assert entry.unique_id == USER_ID


@pytest.mark.parametrize(
    ("code", "reason"),
    [(400, "bike_not_ready"), (402, "no_cellular"), (500, "pairing_failed")],
)
async def test_pairing_code_request_errors(
    hass: HomeAssistant, fake_client: FakeClient, code: int, reason: str
) -> None:
    result = await start_pairing(hass, fake_client)
    fake_client.request_pairing_code.side_effect = PairingError("no", code=code)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pair_start"
    assert result["errors"] == {"base": reason}


async def test_wrong_code(hass: HomeAssistant, fake_client: FakeClient) -> None:
    result = await start_pairing(hass, fake_client)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    fake_client.verify_pairing_code.side_effect = PairingError("wrong", code=4004)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "000000"}
    )
    assert result["step_id"] == "pair_code"
    assert result["errors"] == {"base": "wrong_code"}

    # Too many attempts need a new code
    fake_client.verify_pairing_code.side_effect = PairingError("too many", code=4003)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "000000"}
    )
    assert result["step_id"] == "pair_start"
    assert result["errors"] == {"base": "attempts_exceeded"}

    # A new attempt clears the error
    fake_client.verify_pairing_code.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pair_code"
    assert result["errors"] == {}


async def test_pairing_not_confirmed(
    hass: HomeAssistant, fake_client: FakeClient
) -> None:
    result = await start_pairing(hass, fake_client)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    with patch("custom_components.livewire.config_flow.PAIRING_TIMEOUT", 0):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CODE: "123456"}
        )
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["step_id"] == "pair_start"
    assert result["errors"] == {"base": "not_confirmed"}
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_pick_bike(hass: HomeAssistant, fake_client: FakeClient) -> None:
    fake_client.add_bike("100000002", "7TM3GDYD6SB000001", "Del Mar")
    fake_client.paired = set()

    result = await choose(hass, await start(hass), "pair")
    assert result["step_id"] == "pick_bike"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"bike": "100000002"}
    )
    assert result["step_id"] == "pair_start"
    assert result["description_placeholders"] == {"bike": "2025 S2 Mulholland Del Mar"}

    await hass.config_entries.flow.async_configure(result["flow_id"], {})
    fake_client.request_pairing_code.assert_awaited_once_with("100000002")


async def test_reauth(
    hass: HomeAssistant, fake_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "new@example.com", CONF_PASSWORD: "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data == {
        CONF_USERNAME: "new@example.com",
        CONF_PASSWORD: "new",
        CONF_DEVICE_UUID: DEVICE_UUID,
    }


async def test_reauth_wrong_account(
    hass: HomeAssistant, fake_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    fake_client.user_id = "someone-else"

    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data[CONF_PASSWORD] == "secret"


async def test_reconfigure_device_uuid(
    hass: HomeAssistant, fake_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    new_uuid = str(uuid.uuid4())

    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.MENU

    result = await choose(hass, result, "device_uuid")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_UUID: new_uuid}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_DEVICE_UUID] == new_uuid


async def test_reconfigure_pairs_existing_uuid(
    hass: HomeAssistant, fake_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    fake_client.paired = set()

    result = await config_entry.start_reconfigure_flow(hass)
    result = await choose(hass, result, "pair")
    assert result["step_id"] == "pair_start"

    # The entry's UUID is paired, so other bikes stay paired with it
    assert fake_client.device_uuids[-1] == DEVICE_UUID

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    fake_client.is_paired.side_effect = [True]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "123456"}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_DEVICE_UUID] == DEVICE_UUID


async def test_reconfigure_skip(
    hass: HomeAssistant, fake_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    result = await config_entry.start_reconfigure_flow(hass)
    result = await choose(hass, result, "skip")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_DEVICE_UUID] == DEVICE_UUID
    assert config_entry.data[CONF_PAIRING_SKIPPED] is True


async def test_reconfigure_pairing_after_skip(
    hass: HomeAssistant, fake_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_PAIRING_SKIPPED: True}
    )

    # The bike is paired with the entry's UUID meanwhile
    result = await config_entry.start_reconfigure_flow(hass)
    result = await choose(hass, result, "pair")

    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_PAIRING_SKIPPED] is False


async def test_reconfigure_already_paired(
    hass: HomeAssistant, fake_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    """Choosing a bike that is already paired finishes right away"""

    result = await config_entry.start_reconfigure_flow(hass)
    result = await choose(hass, result, "pair")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    fake_client.request_pairing_code.assert_not_awaited()


async def test_reconfigure_login_fails(
    hass: HomeAssistant, fake_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    fake_client.get_bikes.side_effect = AuthenticationError("Invalid LoginID")

    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_auth"


async def test_options(
    hass: HomeAssistant, fake_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    options = {
        CONF_SCAN_INTERVAL: 10,
        CONF_CHARGING_SCAN_INTERVAL: 2,
        CONF_ADD_COMMAND_ENTITIES: False,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == options
