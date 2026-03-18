"""Data models for Lidl Plus API responses."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Store:
    id: str
    name: str
    address: str
    postal_code: str
    locality: str


@dataclass
class Discount:
    description: str
    amount: float


@dataclass
class Item:
    name: str
    price: float
    vat_group: str
    quantity: float = 1.0
    unit_price: float | None = None
    discounts: list[Discount] = field(default_factory=list)


@dataclass
class Receipt:
    id: str
    date: datetime
    store: Store
    items: list[Item]
    total: float
    currency: str
    payment_method: str | None = None
    vat_breakdown: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass
class Coupon:
    id: str
    title: str
    start_date: datetime
    end_date: datetime
    is_activated: bool
    description: str = ""
    image_url: str | None = None
