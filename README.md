# LiveWire for Home Assistant

A Home Assistant integration for LiveWire electric motorcycles (S2 line: Del Mar,
Mulholland, Alpinista and others), using the cloud API of the LiveWire app through the
[py-livewire](https://github.com/hass-livewire/py-livewire) library.

> This project is not affiliated with LiveWire or Harley-Davidson. It uses an
> undocumented API that may change or stop working at any time.

## Features

For each motorcycle in the account:

| Entity | Description |
|---|---|
| Battery, range, odometer | State of charge, and range and odometer in the units of Home Assistant |
| Charging, plugged in | Whether the bike charges, and whether the charger is plugged in |
| Charge limit, time to charge limit | The limit charging stops at, and how long until it is reached |
| Location | GPS position as a device tracker |
| Front and rear tire pressure | With the recommended pressure as attribute, and "low" problem sensors |
| Vehicle software | Installed and available software version, with release notes |
| Charging schedules | Number of schedules, with the schedules as attribute |
| Paired, tracking status, last reported | Diagnostics |

Command entities (can be turned off in the options):

| Entity | Description |
|---|---|
| Charge limit | Sets the charge limit, 70 to 100% |
| Start charging | Starts charging right away instead of waiting for a charging schedule |
| Enhanced tracking | Reports the bike as stolen, it then sends its position every few minutes. **Disabled by default**, enable it in the entity settings |

Actions to manage the charging schedules: `livewire.add_charging_schedule`,
`livewire.update_charging_schedule` and `livewire.delete_charging_schedule`. The schedule
IDs are in the attributes of the Charging schedules sensor.

The data is polled every 5 minutes, and every minute while a bike charges. Tire
pressures, software versions and charging schedules are refreshed every 30 minutes.

## Installation

1. In [HACS](https://hacs.xyz), add `https://github.com/hass-livewire/hass-livewire` as a
   custom repository of type *Integration*.
2. Install *LiveWire* and restart Home Assistant.
3. Go to **Settings** > **Devices & services** > **Add integration** > **LiveWire**.

## Setup and the device UUID

LiveWire only shares the battery and charging status of a motorcycle with devices that
are **paired** with it. Home Assistant acts as such a device, identified by a *device
UUID*. After logging in with the account of the LiveWire app, there are three options:

- **Pair with my motorcycle**: Home Assistant creates its own device UUID and pairs it.
  You need to be at the bike once:
  1. Switch the ignition on and wait for the display. The bike must not be in
     propulsion mode or charging, and needs cellular reception.
  2. Submit the instructions step: the bike shows a pairing code on its display.
  3. Enter the code. Home Assistant waits up to a minute for the bike to confirm.
- **Use a device UUID that is already paired**, for example the one of the LiveWire app
  on your Android phone. With the phone connected over USB debugging, the
  [py-livewire](https://github.com/hass-livewire/py-livewire) command `livewire
  phone-uuid` reads it from the log of the app.
- **Continue without pairing**: only the entities that need no pairing are created:
  position, tire pressure, software versions, charging schedules and the diagnostics.
  The battery, range, odometer, charging and command entities are left out.

If the device UUID turns out not to be paired with a motorcycle (other than by choosing
to continue without pairing), a repair issue says so.

To pair later, pair another motorcycle of the account, or switch to a different device
UUID, choose **Reconfigure** in the menu of the entry. Pairing there keeps the entry's
device UUID, so motorcycles already paired with it stay paired.

## Options

- **Polling interval**: minutes between updates, 5 by default.
- **Polling interval while charging**: 1 minute by default.
- **Add command entities**: the charge limit, start charging and enhanced tracking
  entities, on by default.

## Notes

- The step of the charge limit is 10%. The app offers 70 to 100%, finer steps were not
  verified.
- A pairing request cannot be cancelled, an unused code expires.
- When the bike cannot be reached, the last known values are kept.

## Development

```sh
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
ruff check . && ruff format --check . && pytest
```

The tests use a fake client and need no account. To also run a read-only test against
your own account, with a device UUID paired with a bike:

```sh
LW_EMAIL=... LW_PASSWORD=... LW_DEVICE_UUID=... pytest tests/live
```
