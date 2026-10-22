"""Charging schedule services"""

from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from py_livewire import LivewireError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.livewire.const import DOMAIN

from .conftest import BIKE_ID, VIN, FakeClient


def device_id(hass: HomeAssistant) -> str:
    [entry] = hass.config_entries.async_entries(DOMAIN)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, VIN), entry.entry_id
    )
    assert device is not None
    return device.id


async def call(hass: HomeAssistant, service: str, **data: Any) -> None:
    await hass.services.async_call(
        DOMAIN,
        service,
        {"device_id": device_id(hass), **data},
        blocking=True,
    )


async def test_add(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    fetched = fake_client.get_charging_schedules.await_count

    await call(
        hass, "add_charging_schedule", days=["mon", "Tue"], start="22:00", end="06:00"
    )

    [args] = fake_client.add_charging_schedule.await_args_list
    assert args.args == (BIKE_ID, ["mon", "tue"], time(22), time(6))
    assert isinstance(args.kwargs["utc_offset_minutes"], int)

    # The schedules are fetched again right away
    assert fake_client.get_charging_schedules.await_count == fetched + 1


async def test_add_needs_days(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    with pytest.raises(vol.Invalid):
        await call(hass, "add_charging_schedule", days=[], start="22:00", end="06:00")


async def test_update(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    # No days disable the schedule
    await call(
        hass,
        "update_charging_schedule",
        schedule_id="s1",
        days=[],
        start="21:00",
        end="05:30",
    )

    [args] = fake_client.update_charging_schedule.await_args_list
    assert args.args == (BIKE_ID, "s1", [], time(21), time(5, 30))


async def test_delete(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    await call(hass, "delete_charging_schedule", schedule_id="s1")
    fake_client.delete_charging_schedule.assert_awaited_once_with(BIKE_ID, "s1")


async def test_unknown_schedule(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "delete_charging_schedule", schedule_id="nope")

    assert err.value.translation_key == "unknown_schedule"
    fake_client.delete_charging_schedule.assert_not_awaited()


async def test_invalid_device(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "delete_charging_schedule",
            {"device_id": "nope", "schedule_id": "s1"},
            blocking=True,
        )
    assert err.value.translation_key == "invalid_device"


async def test_client_error(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.delete_charging_schedule.side_effect = LivewireError("boom")

    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "delete_charging_schedule", schedule_id="s1")
    assert err.value.translation_key == "schedule_failed"
