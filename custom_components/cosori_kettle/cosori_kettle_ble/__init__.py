"""Python library for Cosori Kettle BLE communication."""

from .device import CosoriKettleDevice
from .exceptions import CosoriKettleError, CosoriKettleConnectionError, CosoriKettleTimeoutError

__version__ = "0.1.0"
__all__ = [
    "CosoriKettleDevice",
    "CosoriKettleError",
    "CosoriKettleConnectionError",
    "CosoriKettleTimeoutError",
]
