# Changelog

## Unreleased
- Config flow setup now bounds the whole probe (`PROBE_TIMEOUT`, 60 s): a
  wedged adapter or proxy stuck in `start_notify` or the handshake writes
  previously could hang the setup dialog past every internal deadline. A
  timed-out probe keeps the `cannot_connect`/`no_status` distinction and
  cleanup stays bounded.
- Successful control commands reset the poll-failure backoff cadence, so a
  recovered kettle is retried at the normal interval instead of an
  inflated one.
- The coordinator's dead raw `TimeoutError` handler was removed: the device
  already converts every timeout to `CosoriKettleTimeoutError`.
- A base-dependent poll now bounds its wait for an extended frame
  (`BASE_STATUS_TIMEOUT`, 10 s) instead of consuming the caller's whole
  command budget. A compact-only stream reports "No extended status (with
  the base field) received" — with no heating command written — instead of
  an "outcome is unconfirmed" error that implied a write had happened.
- The `on_base` binary sensor no longer uses the `CONNECTIVITY` device
  class, which rendered a physical on-base state as a network connection
  state.

- A temperature-only request now fetches a fresh extended status before
  deciding whether to start heating. Cached heating state from before a
  manual stop at the kettle previously made `set_target_temperature` replay
  the start transaction — an unintended boil. The base interlock likewise
  acts only on a frame that actually carries the base field, so a compact
  status can no longer satisfy it with a cached value.
- The water heater's `temperature` attribute now reports the setpoint the
  kettle itself is armed to. A pending request is shown separately as the
  `requested_temperature` attribute and on the diagnostic target sensor, so
  a preset staged while off can no longer hide an externally changed
  setpoint indefinitely.
- The poll deadline now bounds the BLE I/O inside the device transaction,
  so waiting for a control command to finish no longer times out the poll
  and marks every entity unavailable on a healthy link. A timed-out
  transaction still drops the wedged client.
- Repeated poll failures back off through `UpdateFailed.retry_after`
  (2 s, 4 s, … capped at 60 s) instead of retry-storming an absent kettle
  every 2 seconds forever.
- `build_ctrl(echo=True)` distinguishes "no status seen" from a legitimate
  status sequence of zero, which a later non-status frame used to replace.
- Test double: HELLO5 now ends a prior stop, so restart-after-stop is
  testable; poll responses can be budgeted for unconfirmed-command tests; a
  fresh subscription marks the mock client connected. New coverage: Bluetooth
  discovery flows, compact frames through the device layer, the sequence-zero
  sentinel, water-reading plausibility boundaries, and unload plus HA shutdown
  with an active poll and an active command.

- A fresh base status is tracked on receipt during a poll, so an extended
  response immediately followed by a compact frame no longer loses the base
  information and times out a start.

- Unload and HA shutdown now cancel in-flight control commands and polls
  instead of awaiting them: the production `COMMAND_TIMEOUT` (30 s) and
  `POLL_TIMEOUT` (15 s) exceed Home Assistant's ~10 s wait for unload
  tasks, which previously returned from unload with the BLE connection
  still held — including when a poll's reconnect was wedged in
  `start_notify()` and holding the device's connection lock.
  `disconnect()` also bounds its wait for a busy transaction
  (`DISCONNECT_LOCK_TIMEOUT`) as a backstop.

- The water heater's `requested_temperature` attribute now renders in the
  configured unit system, like core's `temperature` attribute, instead of
  raw Celsius.
- Packaging: the MIT license classifier was removed alongside PEP 639
  `license = "MIT"`; setuptools 84 rejects the combination.

- `CosoriKettleDevice.connect()` now enforces its own deadline.
  `establish_connection()` ignores a caller `timeout` (it applies its own 20 s
  per-attempt timeout and retries four times), so `CONNECT_TIMEOUT`,
  `COMMAND_CONNECT_TIMEOUT`, and `POLL_CONNECT_TIMEOUT` previously bounded
  nothing and a slow device always ended as a coordinator deadline instead of a
  `CosoriKettleTimeoutError`.
- A staged target is now retired when the kettle contradicts it. If the setpoint
  frame was written and a later status reports a different setpoint, the request
  failed and the reported target follows the kettle again. A staged target that
  was never written stays pending across reconnects, so a start refused off-base
  does not discard it.
- The water heater stays available whenever the Bluetooth link is healthy, so
  `water_heater.turn_off` is never silently dropped. Being off-base now blocks
  only starting heat, and `current_operation` reports the heating flag.
- Custom handshake packets are validated as one assembled registration message:
  length-capped, checksum-valid, complete frames with non-heating opcodes only.
  A stored handshake that fails validation — undecodable hex, a non-sequence, or
  a non-string element — fails setup with a `ConfigEntryError` instead of a crash.
- Sensor and binary sensor names now resolve through `translation_key`, so the
  `entity:` blocks in `strings.json` and `translations/en.json` are actually
  used. The deprecated `show_advanced_options` gate was removed; the optional
  handshake fields are always offered.
- The commanded setpoint sensor no longer claims `MEASUREMENT`, so the Recorder
  does not build statistics for a value only the user changes.
- CI runs the library suite on Python 3.11–3.14; lint (Black, Ruff, library
  MyPy) runs on a library-only install; the Home Assistant suite and the
  Home Assistant-layer MyPy run together on 3.14, where their dependencies
  exist. Workflows declare read-only permissions.

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