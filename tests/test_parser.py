"""Tests for ilidl HTML receipt parser."""

import json
from pathlib import Path

import pytest

from ilidl.exceptions import ReceiptParseError
from ilidl.parser import parse_receipt_html

FIXTURE = Path(__file__).parent / "fixtures" / "receipt_gb_sample.json"


@pytest.fixture
def sample_html():
    data = json.loads(FIXTURE.read_text())
    return data["htmlPrintedReceipt"]


class TestParseItems:
    def test_item_count(self, sample_html):
        result = parse_receipt_html(sample_html)
        assert len(result.items) == 7

    def test_simple_item(self, sample_html):
        result = parse_receipt_html(sample_html)
        beans = next(i for i in result.items if "Beans" in i.name)
        assert beans.name == "Heinz Beans Standard"
        assert beans.price == 2.74
        assert beans.vat_group == "A"
        assert beans.quantity == 1.0

    def test_weight_item(self, sample_html):
        result = parse_receipt_html(sample_html)
        carrots = next(i for i in result.items if "Carrots" in i.name)
        assert carrots.name == "Loose Carrots 0082755"
        assert carrots.price == 0.17
        assert carrots.quantity == 0.24
        assert carrots.unit_price == 0.69

    def test_item_with_discount(self, sample_html):
        result = parse_receipt_html(sample_html)
        handwash = next(i for i in result.items if "Handwash" in i.name)
        assert len(handwash.discounts) == 1
        assert handwash.discounts[0].description == "Price Cut"
        assert handwash.discounts[0].amount == 0.04


class TestParseTotals:
    def test_total(self, sample_html):
        result = parse_receipt_html(sample_html)
        assert result.total == 12.38

    def test_payment_method(self, sample_html):
        result = parse_receipt_html(sample_html)
        assert result.payment_method == "CARD"


class TestParseVat:
    def test_vat_breakdown(self, sample_html):
        result = parse_receipt_html(sample_html)
        assert result.vat_breakdown["A"] == (5.16, 0.00)
        assert result.vat_breakdown["B"] == (7.22, 1.20)


class TestParseError:
    def test_empty_html_raises(self):
        with pytest.raises(ReceiptParseError) as exc_info:
            parse_receipt_html("<html><body></body></html>")
        assert exc_info.value.raw_html == "<html><body></body></html>"

    def test_no_items_raises(self):
        with pytest.raises(ReceiptParseError):
            parse_receipt_html("<html><body><pre></pre></body></html>")
