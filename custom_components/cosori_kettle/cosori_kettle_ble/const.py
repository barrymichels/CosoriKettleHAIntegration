"""Constants for Cosori Kettle BLE protocol."""

from uuid import UUID

# BLE Service and Characteristic UUIDs
SERVICE_UUID = UUID("0000fff0-0000-1000-8000-00805f9b34fb")
RX_CHAR_UUID = UUID("0000fff1-0000-1000-8000-00805f9b34fb")  # Notifications
TX_CHAR_UUID = UUID("0000fff2-0000-1000-8000-00805f9b34fb")  # Write

# Packet frame types
FRAME_TYPE_COMPACT = 0x22  # Compact status (12-byte payload)
FRAME_TYPE_EXTENDED = 0x12  # Extended status (29-byte payload)

# Temperature limits (Fahrenheit)
MIN_TEMP_F = 104
MAX_TEMP_F = 212
MIN_VALID_READING_F = 40
MAX_VALID_READING_F = 230

# Temperature limits (Celsius)
MIN_TEMP_C = 40
MAX_TEMP_C = 100

# Setpoint modes
MODE_BOIL = 0x04  # 212°F / 100°C
MODE_CUSTOM = 0x06  # Other temperatures

# Heating stages
STAGE_IDLE = 0x00
# Non-zero stages indicate active heating

# On-base detection
ON_BASE = 0x00
OFF_BASE = 0x01

# Packet structure
PACKET_HEADER = 0xA5
PACKET_MIN_LENGTH = 6

# Delays (milliseconds)
HELLO_DELAY_MS = 80
COMMAND_DELAY_MS = 100
