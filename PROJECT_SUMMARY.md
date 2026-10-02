# Review and compatibility update

Reviewed against Home Assistant **2026.9.4** (latest stable checked October 1, 2026) and working CosoriKettleBLE commit [`094411bf156e879f6b08106869148c2421856ff4`](https://github.com/barrymichels/CosoriKettleBLE/blob/094411bf156e879f6b08106869148c2421856ff4/components/cosori_kettle_ble/cosori_kettle_ble.cpp).

## Protocol / ESPHome comparison

The original Python implementation could not communicate correctly with the working kettle protocol. Both duplicated library copies had these blockers:

| Original behavior | Corrected behavior from working C++ |
|---|---|
| Unrelated `55 AA` registration packets | Exact default A5 registration split into 20/20/2-byte writes, 80 ms apart |
| XOR checksum | One's-complement additive checksum; complete frame sums to `0xFF` modulo 256 |
| Poll type `02`; preparation/setpoint/control type `05` | Poll, HELLO5, SETPOINT, F4 use `22`; CTRL uses `12` |
| Current/target temperatures from payload offsets 4/5 | Current at 7; target at 6; Fahrenheit on the wire |
| Incorrect heating field | Compact status uses offset 8; extended status uses stage at 4 |
| Compact status forces on-base | Preserve base state; extended offset 14 reports it |
| Assumes one notification is a complete frame | Assemble fragments, process coalesced frames, reject malformed packets |
| Start sends one fresh-sequence CTRL | HELLO5 → SETPOINT → status-sequence CTRL → fresh-sequence reinforcing CTRL |
| Stop changes CTRL payload | F4 → status-sequence CTRL → F4 |
| Temperature selection starts heating | Stage while off; apply while heating or explicitly starting |

TX sequence increment/wrap, RX synchronization, and control delays match the C++ implementation. Custom three-packet registration remains available for firmware that requires it. The C++ is authoritative where `PROTOCOL.md` disagrees: that document describes older command types/checksums and contains an incorrectly framed compact example.

## Home Assistant / lifecycle review

Corrected integration issues:

- Subscribe/register through retry-connector clients supplied by HA's connectable Bluetooth lookup. Resolve the adapter/proxy again on reconnect.
- Serialize complete poll and control transactions, and clear status events before writing so immediate notifications are retained.
- Treat missing valid status as failure; setup cannot succeed on stale/absent data.
- Release clients after subscription/setup failures, cancelled setup, unload, and HA shutdown.
- Use `entry.runtime_data`, pass the config entry into the coordinator, and call its base shutdown method.
- Advertise `OPERATION_MODE`, handle `operation_mode` on temperature actions, and distinguish validation errors from communication failures.
- Publish verified command results without a redundant second poll.
- Keep two targets: a staged request and the reported setpoint. A staged target is shown until the kettle answers — it echoes the setpoint back, or, when the setpoint frame was written and the kettle settled elsewhere, the request failed and the reported target follows the kettle. A staged target that was never written stays pending across reconnects.
- Bound each transaction with `POLL_TIMEOUT` / `COMMAND_TIMEOUT` so a stuck transport cannot stall the refresh cadence, and bound connection establishment itself in `connect()`: `establish_connection()` ignores a caller timeout, applying its own 20 s per-attempt timeout over four attempts, so the advertised `CONNECT_TIMEOUT` / `COMMAND_CONNECT_TIMEOUT` / `POLL_CONNECT_TIMEOUT` budgets are now enforced there. Report a written command whose status never arrived as unconfirmed instead of claiming success or failure.
- Validate a reported setpoint against the 104–212°F range the kettle accepts. A status carrying an uncommandable setpoint reports no target instead of one `turn_on` cannot write, and keeps the valid current temperature and base state.
- Release the BLE client when a transaction is cancelled, so a timed-out write cannot leave a connection marked usable and block the next reconnect onto a fresh proxy route.
- Bound disconnect cleanup with `DISCONNECT_TIMEOUT` (5 s) so an unresponsive `client.disconnect()` cannot hold the transaction locks open indefinitely. A timed-out transaction can still take up to that bound beyond its deadline to release them.
- Validate the kettle status fingerprint during setup because FFF0 advertisements are generic. Accept manual MAC input when the kettle does not advertise that UUID.
- Validate a custom handshake as one assembled registration message: a sequence of hex strings, length-capped, complete checksum-valid frames, and opcodes that cannot command the heating element, because the handshake is replayed on every reconnect for the life of the entry. Anything unusable — a non-sequence, a non-string element, bad hex, or a heating frame — fails as `ValueError`, so a stored handshake that fails validation fails setup with `ConfigEntryError`.
- Keep the water heater available whenever the link is healthy so `turn_off` is never dropped by Home Assistant's unavailable-entity filtering; the base check gates starting heat only, and `current_operation` reports the heating flag.
- Resolve entity names through `translation_key` so the `entity:` blocks in `strings.json` and `translations/en.json` are used, and stop gating the optional handshake fields on the deprecated `show_advanced_options`, which now always returns True and breaks in 2027.6.
- Use the valid `local_polling` IoT class and leave `bleak-retry-connector` unpinned so Home Assistant core supplies the version it already ships; a pinned copy can conflict with core.
- Package the bundled library as the standalone module, removing the second protocol implementation and the need for a separate HA library installation.
- Correct manual installation paths and replace thermostat-card examples with water-heater-compatible entity cards.

Entity unique IDs remain based on the existing entry ID. A staged target is local while off, matching the working ESPHome behavior, and is retired once the kettle confirms or contradicts it. The original `sw_version: 1.0` was fabricated and is removed.

## Verification scope

The regression suite covers literal ESPHome packet bytes and real status captures for both boil and custom modes, framing/checksum failures, immediate fragmented responses, serialized start/stop transactions, timeout cleanup, temperature validation, custom handshake acceptance and rejection, target staging and reconciliation, unconfirmed commands, the poll, command, and connection-establishment deadlines, cancelled-write connection release, bounded disconnect cleanup, uncommandable setpoint rejection, manifest/dependency and distribution-version consistency, actual Home Assistant platform setup and service dispatch, config-flow probing/duplicates, unavailable states, off-base availability and stop delivery, reconnect routing, and lifecycle cleanup.

All 94 collected regression cases pass against Home Assistant 2026.9.4 on Python 3.14; the library suite also runs on 3.11–3.13. Black, Ruff, library MyPy, and Home Assistant-layer MyPy run in CI alongside the suite. Automated transport is a test double, not a physical kettle.

On October 1, 2026, the project owner reported successful setup with a physical kettle after converting the old ESP32 to an active Bluetooth Proxy, connecting its ESPHome API to Home Assistant, and restarting Home Assistant with the integration files present. This confirms setup in that environment; the remaining control and recovery behavior still needs the [hardware checks](README.md#hardware-verification). Live installation and flashing were performed by the owner, separately from the automated tests.
