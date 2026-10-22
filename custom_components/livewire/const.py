"""Constants for the LiveWire integration"""

from datetime import timedelta

DOMAIN: str = "livewire"

CONF_DEVICE_UUID: str = "device_uuid"
# Set when the user chose to continue without pairing the device UUID
CONF_PAIRING_SKIPPED: str = "pairing_skipped"
CONF_CHARGING_SCAN_INTERVAL: str = "charging_scan_interval"
CONF_ADD_COMMAND_ENTITIES: str = "add_command_entities"

# Polling intervals in minutes
DEFAULT_SCAN_INTERVAL: int = 5
DEFAULT_CHARGING_SCAN_INTERVAL: int = 1
DEFAULT_ADD_COMMAND_ENTITIES: bool = True

# How often the data that rarely changes (tire pressure, software versions,
# charging schedules) is refreshed
EXTRA_DATA_INTERVAL = timedelta(minutes=30)

# The charge limit the app offers, in percent
CHARGE_LIMIT_MIN: int = 70
CHARGE_LIMIT_MAX: int = 100
CHARGE_LIMIT_STEP: int = 10

# How long the config flow waits for the bike to confirm a pairing, in seconds
PAIRING_TIMEOUT: float = 60
PAIRING_POLL_INTERVAL: float = 5
