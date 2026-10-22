"""Setup, unload, entity creation and repair issues"""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from py_livewire import AuthenticationError, LivewireError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.livewire.const import (
    CONF_ADD_COMMAND_ENTITIES,
    CONF_CHARGING_SCAN_INTERVAL,
    CONF_PAIRING_SKIPPED,
    DOMAIN,
)

from .conftest import BIKE_ID, VIN, FakeClient

ENTITIES = {
    ("sensor", "battery_level"),
    ("sensor", "range"),
    ("sensor", "odometer"),
    ("sensor", "charge_limit"),
    ("sensor", "time_to_charge_limit"),
    ("sensor", "tracking_status"),
    ("sensor", "last_reported"),
    ("sensor", "tire_pressure_front"),
    ("sensor", "tire_pressure_rear"),
    ("sensor", "charging_schedules"),
    ("binary_sensor", "charging"),
    ("binary_sensor", "plugged_in"),
    ("binary_sensor", "tire_pressure_front_low"),
    ("binary_sensor", "tire_pressure_rear_low"),
    ("binary_sensor", "paired"),
    ("device_tracker", "location"),
    ("update", "software"),
}

COMMAND_ENTITIES = {
    ("number", "charge_limit_setting"),
    ("button", "start_charging"),
    ("switch", "enhanced_tracking"),
}


def registered(hass: HomeAssistant, entry: MockConfigEntry) -> set[tuple[str, str]]:
    prefix = f"{DOMAIN}_{VIN}_"
    return {
        (e.domain, e.unique_id.removeprefix(prefix))
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


async def test_setup(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    assert setup_integration.state is ConfigEntryState.LOADED
    assert registered(hass, setup_integration) == ENTITIES | COMMAND_ENTITIES

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, VIN), setup_integration.entry_id
    )
    assert device is not None
    assert device.manufacturer == "LiveWire"
    assert device.model == "S2 Mulholland"
    assert device.model_id == "S2MH"
    assert device.name == "Mulholland"
    assert device.serial_number == VIN
    assert device.sw_version == "3.2.1"


async def test_without_command_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_ADD_COMMAND_ENTITIES: False}
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert registered(hass, config_entry) == ENTITIES


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.get_bikes.side_effect = AuthenticationError("Invalid LoginID")

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == SOURCE_REAUTH


async def test_connection_failure_retries(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.get_bikes.side_effect = LivewireError("backend down")

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unpaired(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    """Without pairing there is no charging data, and a repair issue tells why"""

    fake_client.paired = set()

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    fake_client.get_charging_status.assert_not_awaited()

    entities = registered(hass, config_entry)
    assert ("sensor", "battery_level") not in entities
    assert ("number", "charge_limit_setting") not in entities
    assert ("device_tracker", "location") in entities

    issue_id = f"not_paired_{BIKE_ID}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders == {"bike": "Mulholland"}

    # Pairing via reconfigure reloads the entry, the issue goes away
    fake_client.paired = {BIKE_ID}
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert ("sensor", "battery_level") in registered(hass, config_entry)

    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_pairing_skipped(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    """Without pairing by choice: the entities that need none, and no issue"""

    fake_client.paired = set()
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_PAIRING_SKIPPED: True}
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    fake_client.get_charging_status.assert_not_awaited()
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"not_paired_{BIKE_ID}") is None

    entities = registered(hass, config_entry)
    assert entities == {
        ("sensor", "last_reported"),
        ("sensor", "tire_pressure_front"),
        ("sensor", "tire_pressure_rear"),
        ("sensor", "charging_schedules"),
        ("binary_sensor", "tire_pressure_front_low"),
        ("binary_sensor", "tire_pressure_rear_low"),
        ("binary_sensor", "paired"),
        ("device_tracker", "location"),
        ("update", "software"),
    }

    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_unload_deletes_issues(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.paired = set()
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"not_paired_{BIKE_ID}") is None


async def test_options_change(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    coordinator = setup_integration.runtime_data

    # Intervals apply without a reload
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            CONF_SCAN_INTERVAL: 10,
            CONF_CHARGING_SCAN_INTERVAL: 3,
        },
    )
    await hass.async_block_till_done()
    assert setup_integration.runtime_data is coordinator
    assert coordinator.update_interval.total_seconds() == 600

    # Command entities need one
    hass.config_entries.async_update_entry(
        setup_integration,
        options={**setup_integration.options, CONF_ADD_COMMAND_ENTITIES: False},
    )
    await hass.async_block_till_done()
    assert setup_integration.runtime_data is not coordinator
    assert setup_integration.state is ConfigEntryState.LOADED
