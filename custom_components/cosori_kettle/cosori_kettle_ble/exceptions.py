"""Exceptions for Cosori Kettle BLE library."""


class CosoriKettleError(Exception):
    """Base exception for Cosori Kettle errors."""


class CosoriKettleConnectionError(CosoriKettleError):
    """Exception for connection errors."""


class CosoriKettleTimeoutError(CosoriKettleError):
    """Exception for timeout errors."""


class CosoriKettleUnconfirmedError(CosoriKettleError):
    """Command was written, but the kettle never reported the resulting status."""
