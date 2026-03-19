"""Unofficial Lidl Plus API client."""

from importlib.metadata import version

from ilidl.client import LidlClient
from ilidl.models import Coupon, Discount, Item, Receipt, Store

__all__ = ["LidlClient", "Coupon", "Discount", "Item", "Receipt", "Store"]
__version__ = version("ilidl")
