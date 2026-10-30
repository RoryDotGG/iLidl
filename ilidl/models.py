"""Data models for the Lidl UK web API."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class Store:
    name: str
    address: str = ""
    postal_code: str = ""
    locality: str = ""


@dataclass
class Discount:
    promotion_id: str
    description: str
    amount: Decimal
    """Saving as a positive amount, e.g. ``0.16`` for a ``-0.16`` receipt line."""


@dataclass
class Item:
    article_id: str
    name: str
    quantity: Decimal
    """Count, or kilograms for weighed goods."""
    unit_price: Decimal
    price: Decimal
    """``quantity * unit_price`` before discounts."""
    vat_group: str
    discounts: list[Discount] = field(default_factory=list)


@dataclass
class Receipt:
    id: str
    date: datetime
    store: Store
    total: Decimal
    article_count: int | None = None
    items: list[Item] = field(default_factory=list)
    """Empty on receipt summaries; filled by ``LidlClient.receipt``."""
    payment_method: str | None = None
    vat_breakdown: dict[str, tuple[Decimal, Decimal]] = field(default_factory=dict)
    """VAT group to ``(gross amount, VAT amount)``."""
    coupons_used: list[str] = field(default_factory=list)
    points: int | None = None


@dataclass
class Coupon:
    id: str
    offer: str
    title: str
    description: str
    start_date: datetime
    end_date: datetime
    is_activated: bool
    is_locked: bool = False
    is_processing: bool = False
    image_url: str | None = None
