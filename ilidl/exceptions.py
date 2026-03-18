"""Custom exceptions for ilidl."""


class ILidlError(Exception):
    """Base exception for all ilidl errors."""


class AuthError(ILidlError):
    """Authentication failed."""


class ReceiptParseError(ILidlError):
    """HTML receipt could not be parsed into structured data."""

    def __init__(self, message: str, raw_html: str) -> None:
        super().__init__(message)
        self.raw_html = raw_html
