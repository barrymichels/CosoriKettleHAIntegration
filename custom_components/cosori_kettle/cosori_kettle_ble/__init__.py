"""Python library for Cosori Kettle BLE communication."""

from .device import CosoriKettleDevice
from .exceptions import (
    CosoriKettleConnectionError,
    CosoriKettleError,
    CosoriKettleTimeoutError,
    CosoriKettleUnconfirmedError,
)
from .protocol import parse_registration_handshake, validate_registration_packets

__version__ = "0.3.1"
__all__ = [
    "CosoriKettleDevice",
    "CosoriKettleError",
    "CosoriKettleConnectionError",
    "CosoriKettleTimeoutError",
    "CosoriKettleUnconfirmedError",
    "parse_registration_handshake",
    "validate_registration_packets",
]
