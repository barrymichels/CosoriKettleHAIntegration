"""Python library for Cosori Kettle BLE communication."""

from .device import CosoriKettleDevice
from .exceptions import (
    CosoriKettleConnectionError,
    CosoriKettleError,
    CosoriKettleTimeoutError,
    CosoriKettleUnconfirmedError,
)

__version__ = "0.3.0"
__all__ = [
    "CosoriKettleDevice",
    "CosoriKettleError",
    "CosoriKettleConnectionError",
    "CosoriKettleTimeoutError",
    "CosoriKettleUnconfirmedError",
]
