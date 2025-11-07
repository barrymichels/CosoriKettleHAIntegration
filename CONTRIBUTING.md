# Contributing to Cosori Kettle HA Integration

Thank you for your interest in contributing to the Cosori Kettle Home Assistant Integration!

## Development Setup

1. **Fork and Clone**
   ```bash
   git clone https://github.com/YOUR_USERNAME/CosoriKettleHAIntegration.git
   cd CosoriKettleHAIntegration
   ```

2. **Create Development Environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -e ".[dev]"
   ```

3. **Link to Home Assistant**
   ```bash
   # Link the custom component to your HA config directory
   ln -s $(pwd)/custom_components/cosori_kettle ~/.homeassistant/custom_components/
   ```

## Code Style

This project uses:
- **Black** for code formatting
- **Ruff** for linting
- **MyPy** for type checking

Run all checks before committing:
```bash
black cosori_kettle_ble/ custom_components/
ruff check cosori_kettle_ble/ custom_components/
mypy cosori_kettle_ble/
```

## Testing

### Manual Testing

1. Restart Home Assistant after code changes
2. Test with a real Cosori Kettle
3. Check logs for errors: `Settings → System → Logs`

### Unit Tests (Coming Soon)

```bash
pytest
pytest --cov=cosori_kettle_ble  # With coverage
```

## Submitting Changes

1. **Create a Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Your Changes**
   - Follow existing code style
   - Add docstrings to new functions/classes
   - Update README if adding features

3. **Test Thoroughly**
   - Test all modified functionality
   - Ensure no regressions
   - Check logs for warnings/errors

4. **Commit Your Changes**
   ```bash
   git add .
   git commit -m "Add feature: description"
   ```

5. **Push and Create PR**
   ```bash
   git push origin feature/your-feature-name
   ```
   Then create a Pull Request on GitHub

## PR Guidelines

- **Title**: Clear, descriptive title (e.g., "Add support for temperature presets")
- **Description**: Explain what changes were made and why
- **Testing**: Describe how you tested the changes
- **Screenshots**: Include screenshots for UI changes
- **Breaking Changes**: Clearly mark any breaking changes

## Areas for Contribution

### High Priority
- [ ] Unit tests for BLE protocol
- [ ] Integration tests with mock BLE device
- [ ] Support for additional Cosori kettle models
- [ ] Improved error handling and recovery
- [ ] Performance optimization

### Medium Priority
- [ ] Additional language translations
- [ ] Enhanced documentation
- [ ] Example automations
- [ ] Dashboard card examples

### Low Priority
- [ ] Custom Lovelace card
- [ ] Advanced features (schedules, etc.)

## Protocol Documentation

If you're working on BLE protocol improvements:

1. Reference the [ESPHome implementation](https://github.com/barrymichels/CosoriKettleBLE)
2. Document any new findings about the protocol
3. Test thoroughly with real hardware
4. Update protocol documentation in code comments

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Help newcomers get started
- Focus on what's best for the project

## Questions?

- Open a [Discussion](https://github.com/barrymichels/CosoriKettleHAIntegration/discussions)
- Check existing [Issues](https://github.com/barrymichels/CosoriKettleHAIntegration/issues)
- Review the [README](README.md) for documentation

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
