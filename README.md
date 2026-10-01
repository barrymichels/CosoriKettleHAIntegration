# Cosori Kettle Home Assistant Integration

Control a Cosori BLE kettle through Home Assistant's Bluetooth integration, using a local adapter or an ESPHome Bluetooth Proxy. The kettle protocol follows the working [CosoriKettleBLE ESPHome implementation](https://github.com/barrymichels/CosoriKettleBLE).

## Requirements

- Home Assistant 2026.9 or newer (tested against **2026.9.4**).
- A Home Assistant Bluetooth adapter or an ESPHome proxy with **active connections** enabled.
- A compatible Cosori BLE kettle within Bluetooth range.
- The old ESPHome kettle client and VeSync/Cosori app must release their connections. The kettle permits only one BLE connection.

This remains a custom integration. Automated tests use simulated BLE hardware; operation with a physical kettle and proxy still needs verification. See [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) for the comparison and validation scope.

## Switching from CosoriKettleBLE

1. Record the kettle MAC address from your working ESPHome `ble_client` configuration. If it has a custom `handshake:` block, save its three packet values too.
2. Turn off the old **Kettle BLE Connection** switch, or remove the old kettle BLE client/component. Close the phone app.
3. Keep your ESP32 if you want to use it as a Bluetooth Proxy. For a permanent conversion, remove the kettle-specific external component, `ble_client`, and entities referencing it, and enable the proxy:

   ```yaml
   esp32_ble_tracker:

   bluetooth_proxy:
     active: true
   ```

   Keep the rest of your board, network, API, and OTA configuration. Flash the updated ESPHome configuration, then ensure the device is connected under **Settings → Devices & services → ESPHome** and appears as a remote adapter in Bluetooth. Device Builder showing it online or its web page responding does not establish this API connection. If necessary, add the ESPHome integration using the device IP and native API port 6053. Match the API encryption setting to the new firmware; leave the encryption key blank for an empty `api:` block. Merely disabling the old client does not turn the ESP32 into a proxy.
4. Install this integration and restart Home Assistant.
5. Add **Cosori Kettle** under **Settings → Devices & services → Add integration**. Select a discovered device or enter the saved MAC address.
6. If needed, enable advanced options in the setup dialog and enter the three custom handshake packets. Default registration matches the working ESPHome project.

Setup connects, registers, and reads valid kettle status before creating the entry. It does not start heating. The service UUID `FFF0` is shared by other BLE products, so an advertisement alone is insufficient to identify a kettle. Manual MAC entry also supports kettles that omit that UUID from their advertisements.

## Installation

Copy the **component directory**, not the whole repository, into Home Assistant's configuration directory:

```bash
# Run from this repository; /config is the Home Assistant configuration directory.
mkdir -p /config/custom_components
cp -r custom_components/cosori_kettle /config/custom_components/
```

The result must include `/config/custom_components/cosori_kettle/manifest.json` and the bundled `cosori_kettle_ble/` directory. Restart Home Assistant. No separate pip installation of the library is needed for Home Assistant.

A HACS custom-repository installation can be used once the updated code is published to the repository. It is not part of the default HACS catalog.

## Entities and controls

| Entity | Purpose |
|---|---|
| `water_heater.cosori_kettle` | Target temperature and on/off control |
| `sensor.cosori_kettle_current_temperature` | Current water temperature |
| `sensor.cosori_kettle_target_temperature` | Selected target; diagnostic, disabled by default |
| `binary_sensor.cosori_kettle_on_base` | Whether the kettle is on its base |
| `binary_sensor.cosori_kettle_heating` | Heating status reported by the kettle |

Actual entity IDs depend on the device name and existing registry entries. Targets range from 40–100°C / 104–212°F, with integer Fahrenheit steps on the wire. Home Assistant displays and accepts temperatures in its configured unit system.

Setting a temperature while off stages the target without starting heating, as in the ESPHome version. Turning on applies that target. Changing the target while heating applies it immediately. Include `operation_mode: "on"` to set a target and start in one action:

```yaml
action: water_heater.set_temperature
target:
  entity_id: water_heater.cosori_kettle
data:
  temperature: 100  # Use 212 if Home Assistant is configured for Fahrenheit.
  operation_mode: "on"
```

Stop heating:

```yaml
action: water_heater.turn_off
target:
  entity_id: water_heater.cosori_kettle
```

Keep-warm behavior is controlled by the kettle firmware. This integration sends the same boil/custom mode and start/stop transactions as the working ESPHome component; it does not implement a separate keep-warm timer.

The water heater becomes unavailable off-base. Its sensors continue reporting off-base status while the BLE connection is alive. Communication failures mark all entities unavailable, and the next poll retries the connection through Home Assistant's current adapter/proxy route.

## Dashboard

Use an entities card and open the water heater's more-info dialog for controls:

```yaml
type: entities
title: Cosori Kettle
entities:
  - water_heater.cosori_kettle
  - sensor.cosori_kettle_current_temperature
  - binary_sensor.cosori_kettle_on_base
  - binary_sensor.cosori_kettle_heating
```

Home Assistant's thermostat card requires a climate entity. This integration exposes a water heater. See [examples/dashboard.yaml](examples/dashboard.yaml) and [examples/automations.yaml](examples/automations.yaml) for additional examples.

For Mushroom preset buttons, use [examples/dashboard-presets.yaml](examples/dashboard-presets.yaml). It provides Black Tea (212°F), Matcha (155°F), Coffee (185°F), and Off buttons with live temperatures and heating colors. This example requires Fahrenheit temperatures in Home Assistant; adjust the entity ID if necessary. It calls the water heater directly, so the old ESPHome preset scripts are not needed by these buttons.

## Hardware verification

After installation, check these with your kettle:

1. Setup succeeds and temperatures agree with the working ESPHome readings.
2. Changing the target while off does not heat; turning on applies the selected target.
3. Both boil and a lower custom temperature start correctly; turn-off stops heating.
4. Removing an idle kettle from its base changes the base sensor to off; compact updates do not reset it to on.
5. Power cycling the kettle or proxy results in unavailable entities, followed by recovery.
6. Disabling/unloading the integration releases its BLE connection so another client can connect.

## Troubleshooting

Setup distinguishes three failures: no connectable Bluetooth route, a BLE connection/registration failure, and a registered connection that returns no valid status. Home Assistant logs record the underlying reason. If there is no route, verify the proxy is connected in the ESPHome integration and appears in Bluetooth before investigating the kettle protocol. For connection/status failures, check for another client holding the kettle connection, unavailable proxy connection slots, or a firmware-specific handshake. Enter the MAC manually if discovery finds nothing. For custom handshakes, copy the three values from your working ESPHome YAML; hexadecimal bytes may contain spaces or colons.

Enable debug logging when collecting failures:

```yaml
logger:
  logs:
    custom_components.cosori_kettle: debug
    bleak_retry_connector: debug
```

## Development

The single BLE library lives under `custom_components/cosori_kettle/cosori_kettle_ble/`. Setuptools also packages that directory as the standalone `cosori_kettle_ble` module, keeping HA and library installs on the same implementation.

See [CONTRIBUTING.md](CONTRIBUTING.md) for test and quality-check commands. Protocol tests use literal packets from the working C++ implementation and captured status frames, including fragmented notifications. Home Assistant tests load the real platforms and call actual services with mocked BLE hardware.

## License

MIT. This project is not affiliated with Cosori.
