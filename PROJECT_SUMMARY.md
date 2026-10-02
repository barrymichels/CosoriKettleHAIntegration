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
- Publish verified command results without a redundant second poll. Staged targets cannot restore availability after a failed connection.
- Keep two targets: a staged request shown until the kettle echoes it, and the reported setpoint, which now follows every status frame. A setpoint changed on the kettle is no longer latched behind the first read.
- Bound each transaction with `POLL_TIMEOUT` / `COMMAND_TIMEOUT` so a stuck transport cannot stall the refresh cadence, and report a written command whose status never arrived as unconfirmed instead of claiming success or failure.
- Validate a reported setpoint against the 104–212°F range the kettle accepts. A status carrying an uncommandable setpoint reports no target instead of one `turn_on` cannot write, and keeps the valid current temperature and base state.
- Release the BLE client when a transaction is cancelled, so a timed-out write cannot leave a connection marked usable and block the next reconnect onto a fresh proxy route.
- Bound disconnect cleanup with `DISCONNECT_TIMEOUT` (5 s) so an unresponsive `client.disconnect()` cannot hold the transaction locks open indefinitely. A timed-out transaction can still take up to that bound beyond its deadline to release them.
- Validate the kettle status fingerprint during setup because FFF0 advertisements are generic. Accept manual MAC input when the kettle does not advertise that UUID.
- Use the valid `local_polling` IoT class and leave `bleak-retry-connector` unpinned so Home Assistant core supplies the version it already ships; a pinned copy can conflict with core.
- Package the bundled library as the standalone module, removing the second protocol implementation and the need for a separate HA library installation.
- Correct manual installation paths and replace thermostat-card examples with water-heater-compatible entity cards.

Entity unique IDs remain based on the existing entry ID. A staged target is local while off, matching the working ESPHome behavior, and is retired once the kettle confirms it; until then the reported setpoint tracks the kettle. The original `sw_version: 1.0` was fabricated and is removed.

## Verification scope

The regression suite covers literal ESPHome packet bytes and real status captures, framing/checksum failures, immediate fragmented responses, serialized start/stop transactions, timeout cleanup, temperature validation, custom handshakes, target staging and reconciliation, unconfirmed commands, the poll and command deadlines, cancelled-write connection release, bounded disconnect cleanup, uncommandable setpoint rejection, manifest/dependency and distribution-version consistency, actual Home Assistant platform setup and service dispatch, config-flow probing/duplicates, unavailable states, reconnect routing, and lifecycle cleanup.

All 46 regression tests pass against Home Assistant 2026.9.4. Black, Ruff, library MyPy, and Home Assistant-layer MyPy run in CI alongside the suite. Automated transport is a test double, not a physical kettle.

On October 1, 2026, the project owner reported successful setup with a physical kettle after converting the old ESP32 to an active Bluetooth Proxy, connecting its ESPHome API to Home Assistant, and restarting Home Assistant with the integration files present. This confirms setup in that environment; the remaining control and recovery behavior still needs the [hardware checks](README.md#hardware-verification). Live installation and flashing were performed by the owner, separately from the automated tests.
