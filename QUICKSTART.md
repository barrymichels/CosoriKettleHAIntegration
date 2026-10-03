# Quick start

Requires Home Assistant 2026.9 or newer and a connectable Bluetooth adapter or active ESPHome Bluetooth Proxy.

1. Save the kettle MAC and any custom handshake from your working ESPHome YAML.
2. Disable the old kettle BLE connection and close the VeSync app. The kettle accepts one connection at a time.
3. If using the old ESP32 as a proxy, configure `bluetooth_proxy: {active: true}` with `esp32_ble_tracker:` and remove its kettle client/component and dependent entities. After flashing, connect it under **Settings → Devices & services → ESPHome** and verify it appears in Bluetooth. Device Builder or the proxy's web page showing it online is insufficient.
4. Copy `custom_components/cosori_kettle/` from this repository into `/config/custom_components/`. The resulting path must be `/config/custom_components/cosori_kettle/manifest.json`.
5. Restart Home Assistant **after copying the folder**, refresh the browser, then add **Cosori Kettle** in **Settings → Devices & services → Add integration**. Select a discovered device or enter the MAC. The form always shows three optional "Custom handshake packet" fields; leave them blank unless you captured custom handshake packets from a working ESPHome configuration.

Setup reads status without heating. Set a target and start using:

```yaml
action: water_heater.set_temperature
target:
  entity_id: water_heater.cosori_kettle
data:
  temperature: 100  # 212 with a Fahrenheit-configured Home Assistant.
  operation_mode: "on"
```

Stop using `water_heater.turn_off`. Setting temperature without an operation mode while off stages it for the next start.

For a dashboard, use an entities card containing `water_heater.cosori_kettle`; open its more-info dialog to control it. The thermostat card requires a climate entity. [Mushroom preset buttons](examples/dashboard-presets.yaml) are also available for Fahrenheit configurations. Verify your entity ID and temperature unit under **Settings → Tools → States** before using examples.

See [README.md](README.md) for migration details, troubleshooting, and the physical-kettle verification steps.
