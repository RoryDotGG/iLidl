"""Custom exceptions for ilidl."""


class ILidlError(Exception):
    """Base exception for all ilidl errors."""


class AuthError(ILidlError):
    """The Lidl web session is missing, unreadable or expired."""


class CouponError(ILidlError):
    """Lidl refused a coupon change (HTTP 412), e.g. not started yet or already active."""

    def __init__(self, coupon_id: str, reason: str) -> None:
        super().__init__(f"Coupon {coupon_id}: {reason}")
        self.coupon_id = coupon_id
        self.reason = reason


class ReceiptParseError(ILidlError):
    """HTML receipt could not be parsed into structured data."""

    def __init__(self, message: str, raw_html: str) -> None:
        super().__init__(message)
        self.raw_html = raw_html
