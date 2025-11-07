# Cosori Kettle Home Assistant Integration

Native Home Assistant integration for Cosori Electric Kettles using Bluetooth Proxy.

## Features

- **Water Heater Entity**: Control your kettle as a native water heater with thermostat card support
- **Temperature Control**: Set target temperature (40-100°C / 104-212°F)
- **Heating Control**: Start/stop heating with one tap
- **Auto Keep Warm**: Kettle automatically maintains temperature at setpoint
- **Status Monitoring**: Real-time temperature, heating state, and on-base detection
- **Bluetooth Proxy Support**: Works with ESPHome Bluetooth Proxies for extended range

## Requirements

- Home Assistant 2023.9 or newer
- Bluetooth adapter or ESPHome Bluetooth Proxy
- Cosori Electric Kettle (BLE-enabled model)

## Installation

### Option 1: Manual Installation (Development)

1. Clone this repository:
   ```bash
   git clone https://github.com/barrymichels/CosoriKettleHAIntegration.git
   cd CosoriKettleHAIntegration
   ```

2. Copy the integration to your Home Assistant config directory:
   ```bash
   cp -r custom_components/cosori_kettle /path/to/your/homeassistant/custom_components/
   ```

3. Copy the library to a location accessible by Home Assistant (or install via pip once published):
   ```bash
   # For development, the integration will use the local library path
   ```

4. Restart Home Assistant

### Option 2: HACS (Coming Soon)

This integration will be available through HACS once published.

## Setup

1. **Ensure Bluetooth is enabled** in Home Assistant (or set up a Bluetooth Proxy)

2. **Power on your Cosori Kettle** and place it on the charging base

3. **Add the integration**:
   - Go to **Settings** → **Devices & Services**
   - Click **+ Add Integration**
   - Search for "Cosori Kettle"
   - Select your kettle from the discovered devices
   - Click **Submit**

4. Your kettle will be added with the following entities:
   - **Water Heater**: Main control interface
   - **Current Temperature Sensor**: Real-time water temperature
   - **Target Temperature Sensor**: Target setpoint (diagnostic)
   - **On Base Binary Sensor**: Indicates if kettle is on charging base
   - **Heating Binary Sensor**: Indicates if kettle is actively heating

## Usage

### Setting Temperature and Starting Heating

**Using the Water Heater Entity:**

1. Click on the water heater entity card
2. Set your desired temperature (40-100°C)
3. Click "Turn On" or set operation mode to "On"

**Via Service Call:**

```yaml
service: water_heater.set_temperature
target:
  entity_id: water_heater.cosori_kettle
data:
  temperature: 100  # °C
  operation_mode: "on"
```

**Via Automation:**

```yaml
automation:
  - alias: "Morning Tea"
    trigger:
      - platform: time
        at: "07:00:00"
    condition:
      - condition: state
        entity_id: binary_sensor.cosori_kettle_on_base
        state: "on"
    action:
      - service: water_heater.set_temperature
        target:
          entity_id: water_heater.cosori_kettle
        data:
          temperature: 100
      - service: water_heater.turn_on
        target:
          entity_id: water_heater.cosori_kettle
```

### Keep Warm Mode

The Cosori Kettle **automatically maintains temperature** when heating is on. After reaching the target temperature, it will cycle on/off to keep the water at the setpoint (±3°F / ±1.5°C).

To enable keep warm:
1. Set your desired temperature
2. Turn on heating
3. The kettle will heat to the target and then maintain it

To disable keep warm:
1. Turn off heating (set operation mode to "Off")

### Automation Examples

**Notify When Water is Ready:**

```yaml
automation:
  - alias: "Kettle Ready Notification"
    trigger:
      - platform: numeric_state
        entity_id: sensor.cosori_kettle_current_temperature
        above: 96  # °C (adjust based on your target)
    condition:
      - condition: state
        entity_id: binary_sensor.cosori_kettle_heating
        state: "on"
      - condition: template
        value_template: >
          {{ (now() - state_attr('automation.kettle_ready_notification', 'last_triggered') | default(now() - timedelta(minutes=10))).total_seconds() > 600 }}
    action:
      - service: notify.mobile_app
        data:
          message: "Your water is ready!"
          title: "Kettle"
```

**Different Temperatures for Different Times:**

```yaml
automation:
  - alias: "Morning Coffee - Boiling"
    trigger:
      - platform: time
        at: "07:00:00"
    condition:
      - condition: state
        entity_id: binary_sensor.cosori_kettle_on_base
        state: "on"
    action:
      - service: water_heater.set_temperature
        target:
          entity_id: water_heater.cosori_kettle
        data:
          temperature: 100  # Boiling for coffee
      - service: water_heater.turn_on
        target:
          entity_id: water_heater.cosori_kettle

  - alias: "Evening Green Tea - Lower Temp"
    trigger:
      - platform: time
        at: "20:00:00"
    condition:
      - condition: state
        entity_id: binary_sensor.cosori_kettle_on_base
        state: "on"
    action:
      - service: water_heater.set_temperature
        target:
          entity_id: water_heater.cosori_kettle
        data:
          temperature: 80  # 80°C for green tea
      - service: water_heater.turn_on
        target:
          entity_id: water_heater.cosori_kettle
```

**Auto-Off When Removed from Base:**

The kettle automatically becomes unavailable when removed from the base. The integration handles this automatically - you don't need to create automations for this.

## Technical Details

### BLE Protocol

This integration communicates with the kettle using Bluetooth Low Energy (BLE):

- **Service UUID**: `0000fff0-0000-1000-8000-00805f9b34fb`
- **Connection Type**: Active connection with notifications
- **Update Interval**: 2 seconds (polling for status)
- **Temperature Range**: 40-100°C (104-212°F)

### Device Behavior

- **Exclusive Connection**: The kettle supports only one BLE connection at a time. You cannot use the Cosori app while Home Assistant is connected.
- **Auto Keep Warm**: The kettle automatically holds temperature when the target is reached - this is the default behavior, not a separate mode.
- **Temperature Accuracy**: Readings may fluctuate ±3°F (±1.5°C) around the setpoint during keep warm mode.
- **On-Base Detection**: Critical for operation - kettle must be on charging base to heat.

### Bluetooth Proxy

For best results, use an ESPHome Bluetooth Proxy:

1. Flash an ESP32 device with ESPHome
2. Enable Bluetooth Proxy component
3. Place the proxy within range of your kettle
4. Home Assistant will automatically use the proxy for communication

Benefits:
- Extended range
- More reliable connection
- Reduced interference

## Troubleshooting

### Kettle Not Discovered

1. Ensure kettle is powered on and on the charging base
2. Verify Bluetooth is enabled in Home Assistant
3. Check that the kettle is within Bluetooth range
4. Try power cycling the kettle (remove from base, wait 10 seconds, replace)
5. Ensure no other device (e.g., Cosori app) is connected to the kettle

### Connection Errors

1. Check Home Assistant logs for errors
2. Restart Home Assistant
3. Remove and re-add the integration
4. Ensure Bluetooth Proxy is online (if using one)

### Temperature Not Updating

1. Verify the kettle is on the base
2. Check that heating is enabled
3. Review logs for communication errors
3. Try restarting the integration

### "Device Unavailable"

This is normal when:
- Kettle is removed from the charging base
- Kettle is out of Bluetooth range
- Another device is connected to the kettle

## Development

This integration is built with two components:

1. **Python Library** (`cosori_kettle_ble/`): BLE protocol implementation using `bleak`
2. **Home Assistant Integration** (`custom_components/cosori_kettle/`): HA-specific code

### Local Development

```bash
# Clone the repository
git clone https://github.com/barrymichels/CosoriKettleHAIntegration.git
cd CosoriKettleHAIntegration

# Link to HA config directory for development
ln -s $(pwd)/custom_components/cosori_kettle ~/.homeassistant/custom_components/

# Restart Home Assistant to load the integration
```

### Running Tests

```bash
# Install development dependencies
pip install -e .

# Run tests (coming soon)
pytest
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Credits

- Based on the [CosoriKettleBLE](https://github.com/barrymichels/CosoriKettleBLE) ESPHome implementation
- Protocol reverse engineering and documentation from the ESPHome project
- Built for submission to [Home Assistant Core](https://github.com/home-assistant/core)

## License

MIT License - See LICENSE file for details

## Support

- **Issues**: [GitHub Issues](https://github.com/barrymichels/CosoriKettleHAIntegration/issues)
- **Discussions**: [GitHub Discussions](https://github.com/barrymichels/CosoriKettleHAIntegration/discussions)

## Disclaimer

This integration is not affiliated with or endorsed by Cosori. Use at your own risk.
