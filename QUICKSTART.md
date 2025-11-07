# Quick Start Guide

Get your Cosori Kettle integrated with Home Assistant in minutes!

## Prerequisites

- ✅ Home Assistant 2023.9 or newer
- ✅ Bluetooth adapter or ESPHome Bluetooth Proxy
- ✅ Cosori Electric Kettle (BLE-enabled)

## Installation

### Method 1: Manual Installation

1. **Copy the integration:**
   ```bash
   cd /config/custom_components/
   git clone https://github.com/barrymichels/CosoriKettleHAIntegration.git cosori_kettle
   ```

2. **Restart Home Assistant**

### Method 2: HACS (Recommended)

1. Open HACS in Home Assistant
2. Click "Integrations"
3. Click the menu (⋮) and select "Custom repositories"
4. Add: `https://github.com/barrymichels/CosoriKettleHAIntegration`
5. Category: Integration
6. Click "Add"
7. Find "Cosori Kettle" and click "Download"
8. Restart Home Assistant

## Setup

1. **Prepare the kettle:**
   - Fill with water
   - Place on charging base
   - Ensure no other apps are connected

2. **Add the integration:**
   - Go to Settings → Devices & Services
   - Click "+ Add Integration"
   - Search for "Cosori Kettle"
   - Select your kettle from the list
   - Click "Submit"

3. **Done!** Your kettle is now integrated

## First Test

Try these commands:

```yaml
# Set temperature to 100°C and start heating
service: water_heater.set_temperature
target:
  entity_id: water_heater.cosori_kettle
data:
  temperature: 100
  operation_mode: "on"

# Stop heating
service: water_heater.turn_off
target:
  entity_id: water_heater.cosori_kettle
```

## Entities Created

After setup, you'll have:

- 🌡️ **water_heater.cosori_kettle** - Main control
- 📊 **sensor.cosori_kettle_current_temperature** - Current temp
- 📊 **sensor.cosori_kettle_target_temperature** - Target temp
- 🔌 **binary_sensor.cosori_kettle_on_base** - On/off base
- 🔥 **binary_sensor.cosori_kettle_heating** - Heating status

## Quick Actions

### Boil Water
```yaml
service: water_heater.set_temperature
data:
  entity_id: water_heater.cosori_kettle
  temperature: 100
  operation_mode: "on"
```

### Green Tea (80°C)
```yaml
service: water_heater.set_temperature
data:
  entity_id: water_heater.cosori_kettle
  temperature: 80
  operation_mode: "on"
```

### Stop Heating
```yaml
service: water_heater.turn_off
target:
  entity_id: water_heater.cosori_kettle
```

## Dashboard Card

Add this to your Lovelace dashboard:

```yaml
type: thermostat
entity: water_heater.cosori_kettle
name: Kettle
```

## Troubleshooting

**Kettle not discovered?**
- Ensure it's on the base and powered
- Check Bluetooth is enabled
- Power cycle the kettle

**Connection errors?**
- Close the Cosori mobile app
- Restart Home Assistant
- Move Bluetooth adapter closer

**More help?** See [README.md](README.md) for full documentation.

## Next Steps

- ✨ Add [automations](examples/automations.yaml) for scheduled heating
- 📱 Set up notifications when water is ready
- 🎨 Customize your [dashboard](examples/dashboard.yaml)

Enjoy your smart kettle! ☕
