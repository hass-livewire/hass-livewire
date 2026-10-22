"""Fixtures for the LiveWire integration tests.

The py-livewire client is replaced by FakeClient, which builds the library's real
models from JSON fixtures, so entities see the same data as with the real client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from py_livewire import (
    Bike,
    ChargingSchedule,
    ChargingStatus,
    Location,
    SoftwareVersion,
    TirePressure,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.livewire.const import (
    CONF_ADD_COMMAND_ENTITIES,
    CONF_CHARGING_SCAN_INTERVAL,
    CONF_DEVICE_UUID,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"

BIKE_ID = "100000001"
VIN = "7TM3GDYD6SB000000"
USER_ID = "user-1"
DEVICE_UUID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


class FakeClient:
    """Stand-in for py_livewire.Client, used as the class and the instance"""

    def __init__(self) -> None:
        # Device UUIDs of the clients created, in order
        self.device_uuids: list[str | None] = []
        self.user_id = USER_ID

        # Responses, as the API sends them
        self.bikes: list[dict[str, Any]] = load_fixture("bikes.json")["bikes"]
        self.charging: dict[str, Any] = load_fixture("charging_status.json")
        self.location: dict[str, Any] = load_fixture("location.json")["data"]
        self.tires: dict[str, Any] = load_fixture("tire_pressure.json")
        self.software: list[dict[str, Any]] = load_fixture("software_versions.json")[
            "bikes"
        ]
        self.schedules: list[dict[str, Any]] = load_fixture("charging_schedules.json")[
            "schedules"
        ]

        # Ids of the bikes the device UUID is paired with
        self.paired: set[str] = {BIKE_ID}

        self.get_bikes = AsyncMock(side_effect=self._get_bikes)
        self.get_charging_status = AsyncMock(
            side_effect=lambda bike_id: ChargingStatus.from_dict(
                copy.deepcopy(self.charging)
            )
        )
        self.get_location = AsyncMock(
            side_effect=lambda bike_id: Location.from_dict(copy.deepcopy(self.location))
        )
        self.get_tire_pressure = AsyncMock(
            side_effect=lambda bike_id, model_code=None: TirePressure.from_dict(
                copy.deepcopy(self.tires)
            )
        )
        self.get_software_versions = AsyncMock(
            side_effect=lambda: [SoftwareVersion.from_dict(s) for s in self.software]
        )
        self.get_charging_schedules = AsyncMock(
            side_effect=lambda bike_id: [
                ChargingSchedule.from_dict(s) for s in self.schedules
            ]
        )
        self.get_software_release_notes = AsyncMock(
            return_value=[
                {
                    "vsbVersion": "3.3.0",
                    "vsbReleaseNote": "Improved range estimation",
                    "releaseDate": "2026-09-01",
                }
            ]
        )

        self.set_charge_limit = AsyncMock()
        self.start_charging = AsyncMock()
        self.set_enhanced_tracking = AsyncMock(return_value="STOLEN")
        self.add_charging_schedule = AsyncMock()
        self.update_charging_schedule = AsyncMock()
        self.delete_charging_schedule = AsyncMock(return_value=True)

        self.request_pairing_code = AsyncMock()
        self.verify_pairing_code = AsyncMock()
        self.is_paired = AsyncMock(side_effect=lambda bike_id: bike_id in self.paired)

    def __call__(
        self, email: str, password: str, device_uuid: str | None = None, **kwargs: Any
    ) -> FakeClient:
        """Used as the Client class: returns itself"""

        self.device_uuids.append(device_uuid)
        return self

    async def _get_bikes(self) -> list[Bike]:
        return [
            Bike.from_dict({**bike, "pairingStatus": bike["id"] in self.paired})
            for bike in copy.deepcopy(self.bikes)
        ]

    def add_bike(self, bike_id: str, vin: str, name: str) -> None:
        self.bikes.append({**self.bikes[0], "id": bike_id, "vin": vin, "name": name})


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading the custom integration in all tests"""


@pytest.fixture
def fake_client() -> Iterator[FakeClient]:
    client = FakeClient()
    with (
        patch("custom_components.livewire.coordinator.Client", client),
        patch("custom_components.livewire.config_flow.Client", client),
    ):
        yield client


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id=USER_ID,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            CONF_DEVICE_UUID: DEVICE_UUID,
        },
        options={
            CONF_SCAN_INTERVAL: 5,
            CONF_CHARGING_SCAN_INTERVAL: 1,
            CONF_ADD_COMMAND_ENTITIES: True,
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> AsyncIterator[MockConfigEntry]:
    """Set up the integration and unload it after the test"""

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    yield config_entry

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
