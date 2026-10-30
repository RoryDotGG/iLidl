"""Unofficial Lidl UK receipts and coupons client."""

from importlib.metadata import version

from ilidl.client import LidlClient
from ilidl.exceptions import AuthError, CouponError, ILidlError, ReceiptParseError
from ilidl.models import Coupon, Discount, Item, Receipt, Store

__all__ = [
    "AuthError",
    "Coupon",
    "CouponError",
    "Discount",
    "ILidlError",
    "Item",
    "LidlClient",
    "Receipt",
    "ReceiptParseError",
    "Store",
]
__version__ = version("ilidl")
