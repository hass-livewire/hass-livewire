"""States of the entities and the commands they send"""

from __future__ import annotations

from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_OFF,
    STATE_ON,
    UnitOfLength,
    UnitOfPressure,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_conversion import DistanceConverter, PressureConverter
from py_livewire import LivewireError, NotPairedError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.livewire.const import DOMAIN

from .conftest import BIKE_ID, VIN, FakeClient


def entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    entity = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{DOMAIN}_{VIN}_{key}"
    )
    assert entity is not None, key
    return entity


def state(hass: HomeAssistant, platform: str, key: str):
    current = hass.states.get(entity_id(hass, platform, key))
    assert current is not None, key
    return current


def converted(state_obj, value: float, unit: str, converter) -> float:
    """The value in the unit the state is shown in"""
    return converter.convert(
        value, unit, state_obj.attributes[ATTR_UNIT_OF_MEASUREMENT]
    )


async def test_sensors(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    assert float(state(hass, "sensor", "battery_level").state) == 50
    assert state(hass, "sensor", "charge_limit").state == "90"
    assert float(state(hass, "sensor", "time_to_charge_limit").state) == 0
    assert state(hass, "sensor", "tracking_status").state == "safe"
    assert state(hass, "sensor", "last_reported").state == "2026-09-11T16:23:56+00:00"

    # Miles from the API, shown in the units of Home Assistant
    for key, miles in (("range", 44), ("odometer", 1000.5)):
        current = state(hass, "sensor", key)
        assert float(current.state) == pytest.approx(
            converted(current, miles, UnitOfLength.MILES, DistanceConverter)
        )

    front = state(hass, "sensor", "tire_pressure_front")
    assert float(front.state) == pytest.approx(
        converted(front, 36, UnitOfPressure.PSI, PressureConverter)
    )
    assert front.attributes["recommended"] == 36

    schedules = state(hass, "sensor", "charging_schedules")
    assert schedules.state == "1"
    assert schedules.attributes["schedules"] == [
        {
            "id": "s1",
            "status": "ACTIVE",
            "days": ["Mon", "Tue"],
            "start": "22:00",
            "end": "06:00",
        }
    ]


async def test_binary_sensors(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    assert state(hass, "binary_sensor", "charging").state == STATE_OFF
    assert state(hass, "binary_sensor", "plugged_in").state == STATE_OFF
    assert state(hass, "binary_sensor", "tire_pressure_front_low").state == STATE_OFF
    assert state(hass, "binary_sensor", "tire_pressure_rear_low").state == STATE_ON
    assert state(hass, "binary_sensor", "paired").state == STATE_ON


async def test_location(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    location = state(hass, "device_tracker", "location")
    assert location.attributes["latitude"] == 48.1371
    assert location.attributes["longitude"] == 11.5754
    assert location.attributes["altitude"] == 510.5
    assert location.attributes["source_type"] == "gps"


async def test_software_update(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_client: FakeClient,
    hass_ws_client: WebSocketGenerator,
) -> None:
    software = state(hass, "update", "software")
    assert software.state == STATE_ON
    assert software.attributes["installed_version"] == "3.2.1"
    assert software.attributes["latest_version"] == "3.3.0"

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "update/release_notes", "entity_id": software.entity_id}
    )
    result = await client.receive_json()
    assert result["result"] == "Improved range estimation"
    fake_client.get_software_release_notes.assert_awaited_once_with(BIKE_ID, ["3.3.0"])


async def test_charge_limit(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    number = entity_id(hass, "number", "charge_limit_setting")
    assert hass.states.get(number).state == "90"

    refreshes = fake_client.get_bikes.await_count
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: number, ATTR_VALUE: 80},
        blocking=True,
    )
    await hass.async_block_till_done()

    fake_client.set_charge_limit.assert_awaited_once_with(BIKE_ID, 80)
    assert fake_client.get_bikes.await_count > refreshes


@pytest.mark.parametrize(
    ("error", "translation_key"),
    [
        (LivewireError("boom"), "set_charge_limit_failed"),
        (NotPairedError("Command manager api failed", code="3000"), "not_reachable"),
    ],
)
async def test_command_errors(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_client: FakeClient,
    error: Exception,
    translation_key: str,
) -> None:
    fake_client.set_charge_limit.side_effect = error

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {
                ATTR_ENTITY_ID: entity_id(hass, "number", "charge_limit_setting"),
                ATTR_VALUE: 80,
            },
            blocking=True,
        )
    assert err.value.translation_key == translation_key


async def test_start_charging(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: entity_id(hass, "button", "start_charging")},
        blocking=True,
    )
    fake_client.start_charging.assert_awaited_once_with(BIKE_ID)


async def test_enhanced_tracking(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    registry = er.async_get(hass)
    switch = entity_id(hass, "switch", "enhanced_tracking")

    # It reports the bike stolen, so it is not enabled by default
    assert (
        registry.async_get(switch).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    )

    registry.async_update_entity(switch, disabled_by=None)
    assert await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(switch).state == STATE_OFF

    fake_client.charging["trackingStatus"] = "STOLEN"
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: switch}, blocking=True
    )
    await hass.async_block_till_done()

    fake_client.set_enhanced_tracking.assert_awaited_once_with(BIKE_ID, True)
    assert hass.states.get(switch).state == STATE_ON

    fake_client.charging["trackingStatus"] = "PENDING"
    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: switch}, blocking=True
    )
    fake_client.set_enhanced_tracking.assert_awaited_with(BIKE_ID, False)

    # The refresh requested by the command is debounced after the previous one
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    # Unknown while the bike has not confirmed the change
    assert hass.states.get(switch).state == "unknown"
