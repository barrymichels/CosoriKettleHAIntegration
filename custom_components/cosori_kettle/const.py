"""Constants for the Cosori Kettle integration."""

from typing import Final

from .cosori_kettle_ble.const import SERVICE_UUID as _SERVICE_UUID

DOMAIN: Final = "cosori_kettle"

# Configuration
CONF_HANDSHAKE: Final = "handshake"

# Update intervals
UPDATE_INTERVAL: Final = 2  # seconds

# Strict deadlines so one stuck transaction cannot dominate the refresh cadence
POLL_TIMEOUT: Final = 15.0  # whole poll, including reconnection
POLL_CONNECT_TIMEOUT: Final = 8.0  # a single poll's connection attempt
COMMAND_TIMEOUT: Final = 30.0  # whole control transaction, including verification
PROBE_TIMEOUT: Final = 60.0  # whole config-flow probe, connect through status

# BLE service UUID for discovery
SERVICE_UUID: Final = _SERVICE_UUID

# Device info
MANUFACTURER: Final = "Cosori"
MODEL: Final = "Electric Kettle"
