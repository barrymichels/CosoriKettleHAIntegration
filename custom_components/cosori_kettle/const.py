"""Constants for the Cosori Kettle integration."""

from typing import Final

DOMAIN: Final = "cosori_kettle"

# Configuration
CONF_HANDSHAKE: Final = "handshake"

# Update intervals
UPDATE_INTERVAL: Final = 2  # seconds

# BLE service UUID for discovery
SERVICE_UUID: Final = "0000fff0-0000-1000-8000-00805f9b34fb"

# Device info
MANUFACTURER: Final = "Cosori"
MODEL: Final = "Electric Kettle"
