"""Tests for ilidl CLI."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ilidl.cli import cli
from ilidl.models import Coupon, Discount, Item, Receipt, Store


def _sample_receipt():
    return Receipt(
        id="receipt123",
        date=datetime(2026, 3, 18, 19, 26, 50),
        store=Store(
            id="GB1459",
            name="Llandaff",
            address="Station Road",
            postal_code="CF14 2FB",
            locality="Cardiff",
        ),
        items=[
            Item(name="Heinz Beans", price=2.74, vat_group="A"),
            Item(
                name="Handwash",
                price=0.59,
                vat_group="B",
                discounts=[Discount(description="Price Cut", amount=0.04)],
            ),
        ],
        total=3.29,
        currency="GBP",
        payment_method="CARD",
    )


def _sample_coupon():
    return Coupon(
        id="coupon123",
        title="Free Pizza",
        start_date=datetime(2026, 3, 1),
        end_date=datetime(2026, 3, 31),
        is_activated=False,
        description="Buy 1 get 1 free",
    )


class TestReceiptCommand:
    @patch("ilidl.cli._get_client")
    def test_receipt_latest_json(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.latest_receipt.return_value = _sample_receipt()
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["receipt", "latest", "--json"])
        assert result.exit_code == 0
        assert "Heinz Beans" in result.output
        assert "2.74" in result.output

    @patch("ilidl.cli._get_client")
    def test_receipt_latest_table(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.latest_receipt.return_value = _sample_receipt()
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["receipt", "latest"])
        assert result.exit_code == 0
        assert "Llandaff" in result.output
        assert "Heinz Beans" in result.output


class TestCouponsCommand:
    @patch("ilidl.cli._get_client")
    def test_coupons_list(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.coupons.return_value = [_sample_coupon()]
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["coupons", "list"])
        assert result.exit_code == 0
        assert "Free Pizza" in result.output
