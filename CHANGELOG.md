# Changelog

## 0.3.0

Breaking changes to the `cosori_kettle_ble` library. The Home Assistant
integration ships this library and is updated for every change below. The
removed constants were importable but unused inside the library, and this
project has no callers for them, so no compatibility aliases are kept.

The integration's `manifest.json`, `pyproject.toml`, and the library's
`__version__` all report 0.3.0; a test asserts they stay equal.

- `SERVICE_UUID`, `RX_CHAR_UUID`, and `TX_CHAR_UUID` are lowercase `str`,
  matching the identifiers bleak and Home Assistant Bluetooth use. Wrap in
  `uuid.UUID(...)` if a caller needs the old type.
- `KettleStatus.target_temp_f` is `float | None`. A status frame whose setpoint
  falls outside the 104–212°F range the kettle accepts now reports `None`
  instead of a number no command can write, while keeping the valid current
  temperature and base state.
- Removed unused constants: `MIN_TEMP_F`, `MAX_TEMP_F`, `STAGE_IDLE`,
  `ON_BASE`, `OFF_BASE`, `PACKET_MIN_LENGTH`, `HELLO_DELAY_MS`,
  `COMMAND_DELAY_MS`. Replacements: `MIN_SETPOINT_F` / `MAX_SETPOINT_F`
  (same 104 / 212 values), `MIN_VALID_READING_F` / `MAX_VALID_READING_F` for
  status plausibility, and `HANDSHAKE_DELAY_S`, `HELLO5_DELAY_S`,
  `SETPOINT_GAP_DELAY_S`, `STATUS_CONFIRM_TIMEOUT_S`, `CTRL_DELAY_S` for the
  real command pacing.
- Added `CosoriKettleUnconfirmedError`: raised when a command was written but
  the kettle reported no status afterwards, so its outcome is unknown.
- Added `CONNECT_TIMEOUT`, `COMMAND_CONNECT_TIMEOUT`, and `DISCONNECT_TIMEOUT`
  in `cosori_kettle_ble.device`. `connect()` keeps its `timeout` argument;
  commands now use the shorter connect bound.

Behavior changes:

- A cancelled or timed-out transaction releases its BLE client, so the next
  poll resolves a fresh adapter or proxy route instead of reusing a connection
  whose write was cancelled.
- `client.disconnect()` cleanup is bounded by `DISCONNECT_TIMEOUT` (5 s). A
  timed-out transaction releases its locks within a known extra window instead
  of waiting on an unresponsive BLE stack indefinitely, so a deadline can be
  exceeded by up to that bound.
- The reported setpoint follows every status frame. A staged request is shown
  only until the kettle echoes that setpoint back, so a target changed on the
  kettle itself is no longer latched behind the first read.

## 0.2.0

Protocol layer rewritten to match the working ESPHome implementation: A5
framing with an additive checksum, correct frame types and payload offsets,
fragmented notification assembly, the HELLO5 → SETPOINT → CTRL start sequence,
the F4 stop sequence, and staged temperature selection.

## 0.1.0

Initial library, bundled inside the Home Assistant integration. Its framing,
checksum, and payload offsets did not match the working kettle protocol.