"""Tests for ilidl models."""

from datetime import datetime

from ilidl.models import Coupon, Discount, Item, Receipt, Store


class TestItem:
    def test_defaults(self):
        item = Item(name="Beans", price=2.74, vat_group="A")
        assert item.quantity == 1.0
        assert item.unit_price is None
        assert item.discounts == []

    def test_weight_item(self):
        item = Item(
            name="Loose Carrots",
            price=0.17,
            vat_group="A",
            quantity=0.24,
            unit_price=0.69,
        )
        assert item.quantity == 0.24
        assert item.unit_price == 0.69

    def test_item_with_discount(self):
        discount = Discount(description="Price Cut", amount=0.04)
        item = Item(
            name="Handwash",
            price=0.59,
            vat_group="B",
            discounts=[discount],
        )
        assert len(item.discounts) == 1
        assert item.discounts[0].amount == 0.04


class TestReceipt:
    def test_minimal(self):
        store = Store(
            id="GB1459",
            name="Llandaff",
            address="Station Road",
            postal_code="CF14 2FB",
            locality="Cardiff",
        )
        receipt = Receipt(
            id="123",
            date=datetime(2026, 3, 18, 19, 26, 50),
            store=store,
            items=[],
            total=12.38,
            currency="GBP",
        )
        assert receipt.payment_method is None
        assert receipt.vat_breakdown == {}


class TestCoupon:
    def test_defaults(self):
        coupon = Coupon(
            id="abc",
            title="Free item",
            start_date=datetime(2026, 3, 1),
            end_date=datetime(2026, 3, 31),
            is_activated=False,
        )
        assert coupon.description == ""
        assert coupon.image_url is None
