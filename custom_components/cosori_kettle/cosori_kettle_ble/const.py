"""Constants for Cosori Kettle BLE protocol."""

# BLE Service and Characteristic UUIDs
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
RX_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"  # Notifications
TX_CHAR_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"  # Write

# Packet frame types
FRAME_TYPE_COMPACT = 0x22  # Compact status (12-byte payload)
FRAME_TYPE_EXTENDED = 0x12  # Extended status (29-byte payload)

# Packet structure
PACKET_HEADER = 0xA5

# Setpoint limits the kettle accepts, in the Fahrenheit wire unit
MIN_SETPOINT_F = 104
MAX_SETPOINT_F = 212

# Plausible temperature readings, used to reject corrupt status frames
MIN_VALID_READING_F = 40
MAX_VALID_READING_F = 230

# Temperature limits exposed to Home Assistant (Celsius)
MIN_TEMP_C = 40
MAX_TEMP_C = 100

# Setpoint modes
MODE_BOIL = 0x04  # 212°F / 100°C
MODE_CUSTOM = 0x06  # Other temperatures

# Frame opcodes (payload byte 1). Registration and status requests are safe to
# replay on every reconnect; 0x41 control, 0xF0 setpoint, 0xF2 prepare and 0xF4
# stop all command the heating element.
OP_REGISTRATION = 0x81
OP_POLL = 0x40
HANDSHAKE_OPS = (OP_REGISTRATION, OP_POLL)

# A custom handshake is one registration message, not an arbitrary script
MAX_HANDSHAKE_BYTES = 256

# Command pacing, matching the working C++ implementation
HANDSHAKE_DELAY_S = 0.08
HELLO5_DELAY_S = 0.06
SETPOINT_GAP_DELAY_S = 0.1
STATUS_CONFIRM_TIMEOUT_S = 2.0
CTRL_DELAY_S = 0.05
