"""Polling: cached data on failures, throttled extra data, charging interval"""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from py_livewire import LivewireError, NotPairedError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.livewire.const import DOMAIN

from .conftest import BIKE_ID, FakeClient
from .test_entities import state


async def test_failed_update_keeps_data(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    coordinator = setup_integration.runtime_data
    fake_client.get_bikes.side_effect = LivewireError("backend down")

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success
    assert float(state(hass, "sensor", "battery_level").state) == 50


async def test_failed_request_keeps_value(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    coordinator = setup_integration.runtime_data
    fake_client.charging["bikeChargingData"]["batteryPercentage"] = 60
    fetch = fake_client.get_charging_status.side_effect

    # Unreachable bike, then a backend error: the last value stays
    for error in (
        NotPairedError("Command manager api failed", code="3000"),
        LivewireError("backend down"),
    ):
        fake_client.get_charging_status.side_effect = error
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert float(state(hass, "sensor", "battery_level").state) == 50

    fake_client.get_charging_status.side_effect = fetch
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert float(state(hass, "sensor", "battery_level").state) == 60


async def test_unpaired_later(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """When the pairing is removed, the charging data is gone and an issue raised"""

    fake_client.paired = set()
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert state(hass, "sensor", "battery_level").state == STATE_UNKNOWN
    assert state(hass, "binary_sensor", "paired").state == "off"
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"not_paired_{BIKE_ID}")


async def test_removed_bike(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.bikes = []
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert state(hass, "sensor", "battery_level").state == STATE_UNAVAILABLE


async def test_extra_data_throttled(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_client: FakeClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    coordinator = setup_integration.runtime_data
    assert fake_client.get_tire_pressure.await_count == 1

    await coordinator.async_refresh()
    assert fake_client.get_tire_pressure.await_count == 1
    assert fake_client.get_charging_status.await_count == 2

    freezer.tick(timedelta(minutes=31))
    await coordinator.async_refresh()
    assert fake_client.get_tire_pressure.await_count == 2
    assert fake_client.get_software_versions.await_count == 2
    assert fake_client.get_charging_schedules.await_count == 2


async def test_charging_interval(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    coordinator = setup_integration.runtime_data
    assert coordinator.update_interval == timedelta(minutes=5)

    fake_client.charging["bikeChargingData"]["chargingStatus"] = True
    await coordinator.async_refresh()
    assert coordinator.update_interval == timedelta(minutes=1)

    fake_client.charging["bikeChargingData"]["chargingStatus"] = False
    await coordinator.async_refresh()
    assert coordinator.update_interval == timedelta(minutes=5)
