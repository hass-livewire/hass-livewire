"""Read-only test against the real LiveWire backend.

Skipped unless LW_EMAIL, LW_PASSWORD and LW_DEVICE_UUID (paired with a bike) are set.
Only the polling requests are sent, nothing is changed on the account or the bikes.
Values are not printed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
import os
import socket
from unittest.mock import patch

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component import plugins
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest_socket

from custom_components.livewire.const import CONF_DEVICE_UUID, DOMAIN

ENV = ("LW_EMAIL", "LW_PASSWORD", "LW_DEVICE_UUID")

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(name) for name in ENV),
    reason="needs LW_EMAIL, LW_PASSWORD and LW_DEVICE_UUID",
)


@pytest.fixture(autouse=True)
def allow_network() -> Iterator[None]:
    """Lift the test harness's block on network access and DNS"""

    blocked = socket.getaddrinfo
    pytest_socket._remove_restrictions()
    socket.getaddrinfo = plugins._real_getaddrinfo

    yield

    socket.getaddrinfo = blocked


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    """A session of the test's loop: the resolver of the shared session of the
    test harness is bound to another one"""

    async with aiohttp.ClientSession() as session:
        with patch(
            "custom_components.livewire.coordinator.async_get_clientsession",
            return_value=session,
        ):
            yield session


async def test_live(hass: HomeAssistant, session: aiohttp.ClientSession) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="live",
        data={
            CONF_USERNAME: os.environ["LW_EMAIL"],
            CONF_PASSWORD: os.environ["LW_PASSWORD"],
            CONF_DEVICE_UUID: os.environ["LW_DEVICE_UUID"],
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    states = {}
    for item in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if item.disabled_by is None:
            key = item.unique_id.split("_", 2)[2]
            states[(item.domain, key)] = hass.states.get(item.entity_id)

    # The device UUID is paired, so the charging data is there
    assert states[("binary_sensor", "paired")].state == STATE_ON
    for key in ("battery_level", "range", "odometer"):
        float(states[("sensor", key)].state)

    assert states[("device_tracker", "location")].attributes.get("latitude") is not None

    # A button is unknown until it is pressed
    unavailable = sorted(
        f"{domain}.{key}"
        for (domain, key), state in states.items()
        if domain != "button"
        and (state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN))
    )
    assert not unavailable, unavailable

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
