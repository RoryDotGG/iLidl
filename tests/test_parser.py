"""Tests for ilidl HTML receipt parser."""

from decimal import Decimal
from pathlib import Path

import pytest

from ilidl.exceptions import ReceiptParseError
from ilidl.models import Discount
from ilidl.parser import parse_receipt_html

HTML = (Path(__file__).parent / "fixtures" / "receipt_gb.html").read_text()


def test_items_skip_weighed_goods_weight_line():
    result = parse_receipt_html(HTML)
    assert [i.article_id for i in result.items] == ["5200601", "0001787", "0008028", "0080755"]


def test_multibuy():
    rice = parse_receipt_html(HTML).items[0]
    assert (rice.quantity, rice.unit_price, rice.price) == (
        Decimal(2),
        Decimal("0.55"),
        Decimal("1.10"),
    )
    assert rice.vat_group == "A"


def test_weighed_item_rounds_line_total():
    potatoes = parse_receipt_html(HTML).items[3]
    assert potatoes.quantity == Decimal("0.692")
    assert potatoes.price == Decimal("0.82")


def test_item_without_quantity_is_one():
    biscuits = parse_receipt_html(HTML).items[1]
    assert (biscuits.quantity, biscuits.price) == (1, Decimal("0.49"))


def test_discounts_attach_to_article_above():
    items = parse_receipt_html(HTML).items
    assert items[0].discounts == [
        Discount("100001006-GB-TEMPLATE-GBAS000000001-1", "15% off coupon", Decimal("0.16"))
    ]
    assert items[2].discounts == [
        Discount("100001000-GB-TEMPLATE-GBOF000000002-2", "£1 off with Lidl Plus", Decimal("1.00"))
    ]
    assert items[3].discounts == []


def test_old_style_discount_without_discount_class():
    biscuits = parse_receipt_html(HTML).items[1]
    assert biscuits.discounts == [Discount("", "Price Cut", Decimal("0.04"))]


def test_line_totals_less_discounts_equal_total():
    result = parse_receipt_html(HTML)
    net = sum(i.price - sum(d.amount for d in i.discounts) for i in result.items)
    assert net == result.total == Decimal("4.00")


def test_payment_and_vat():
    result = parse_receipt_html(HTML)
    assert result.payment_method == "CARD"
    assert result.vat_breakdown == {
        "A": (Decimal("2.21"), Decimal("0.00")),
        "B": (Decimal("1.79"), Decimal("0.30")),
    }


def test_no_items_raises():
    with pytest.raises(ReceiptParseError, match="No items"):
        parse_receipt_html("<html><body><pre></pre></body></html>")


def test_cut_off_total_falls_back_to_line_sum():
    html = HTML.replace('class="css_bold">4.00<', 'class="css_bold">4.0<')
    assert parse_receipt_html(html).total == Decimal("4.00")


def test_weight_line_sharing_the_item_line_id_is_skipped():
    html = HTML.replace('id="purchase_list_line_9"', 'id="purchase_list_line_8"')
    assert len(parse_receipt_html(html).items) == 4
