"""Tests for ilidl CLI."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests
from click.testing import CliRunner

from ilidl.cli import _json_serial, cli
from ilidl.models import Coupon, Discount, Item, Receipt, Store


def _sample_receipt(**overrides):
    defaults = {
        "id": "receipt123",
        "date": datetime(2026, 3, 18, 19, 26, 50),
        "store": Store(
            id="GB1459",
            name="Llandaff",
            address="Station Road",
            postal_code="CF14 2FB",
            locality="Cardiff",
        ),
        "items": [
            Item(name="Heinz Beans", price=2.74, vat_group="A"),
            Item(
                name="Handwash",
                price=0.59,
                vat_group="B",
                discounts=[Discount(description="Price Cut", amount=0.04)],
            ),
        ],
        "total": 3.29,
        "currency": "GBP",
        "payment_method": "CARD",
    }
    defaults.update(overrides)
    return Receipt(**defaults)


def _sample_coupon(**overrides):
    defaults = {
        "id": "coupon123",
        "title": "Free Pizza",
        "start_date": datetime(2026, 3, 1),
        "end_date": datetime(2026, 3, 31),
        "is_activated": False,
        "description": "Buy 1 get 1 free",
    }
    defaults.update(overrides)
    return Coupon(**defaults)


class TestJsonSerial:
    def test_serialises_datetime(self):
        dt = datetime(2026, 3, 18, 19, 26, 50)
        assert _json_serial(dt) == "2026-03-18T19:26:50"

    def test_raises_for_unsupported_type(self):
        with pytest.raises(TypeError, match="not serializable"):
            _json_serial(set())


class TestGetClient:
    @patch("ilidl.cli.Config")
    def test_not_logged_in(self, mock_config_cls):
        mock_config_cls.return_value.refresh_token = ""
        runner = CliRunner()
        result = runner.invoke(cli, ["receipts"])
        assert result.exit_code == 1
        assert "Not logged in" in result.output


class TestReceiptCommand:
    @patch("ilidl.cli._get_client")
    def test_receipt_latest_json(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.latest_receipt.return_value = _sample_receipt()
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["receipt", "latest", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "receipt123"
        assert data["total"] == 3.29

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
        assert "Price Cut" in result.output
        assert "Paid by: CARD" in result.output
        assert "TOTAL" in result.output

    @patch("ilidl.cli._get_client")
    def test_receipt_by_id(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.receipt.return_value = _sample_receipt()
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["receipt", "abc123"])
        assert result.exit_code == 0
        mock_client.receipt.assert_called_once_with("abc123")

    @patch("ilidl.cli._get_client")
    def test_receipt_table_shows_quantity(self, mock_get_client):
        receipt = _sample_receipt(
            items=[
                Item(
                    name="Loose Carrots",
                    price=0.17,
                    vat_group="A",
                    quantity=0.24,
                    unit_price=0.69,
                ),
            ],
            total=0.17,
        )
        mock_client = MagicMock()
        mock_client.latest_receipt.return_value = receipt
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["receipt", "latest"])
        assert result.exit_code == 0
        assert "0.24" in result.output

    @patch("ilidl.cli._get_client")
    def test_receipt_table_no_payment_method(self, mock_get_client):
        receipt = _sample_receipt(payment_method=None)
        mock_client = MagicMock()
        mock_client.latest_receipt.return_value = receipt
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["receipt", "latest"])
        assert result.exit_code == 0
        assert "Paid by" not in result.output


class TestReceiptsCommand:
    @patch("ilidl.cli._get_client")
    def test_receipts_table(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.receipts.return_value = [_sample_receipt()]
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["receipts"])
        assert result.exit_code == 0
        assert "2026-03-18" in result.output
        assert "Llandaff" in result.output
        assert "3.29" in result.output

    @patch("ilidl.cli._get_client")
    def test_receipts_json(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.receipts.return_value = [_sample_receipt()]
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["receipts", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "receipt123"

    @patch("ilidl.cli._get_client")
    def test_receipts_empty(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.receipts.return_value = []
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["receipts"])
        assert result.exit_code == 0
        assert "No receipts found" in result.output

    @patch("ilidl.cli._get_client")
    def test_receipts_date_filter_from(self, mock_get_client):
        old = _sample_receipt(
            id="old",
            date=datetime(2026, 1, 1, 10, 0, 0),
        )
        new = _sample_receipt(
            id="new",
            date=datetime(2026, 3, 18, 19, 26, 50),
        )
        mock_client = MagicMock()
        mock_client.receipts.return_value = [old, new]
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["receipts", "--from", "2026-03-01", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "new"

    @patch("ilidl.cli._get_client")
    def test_receipts_date_filter_to(self, mock_get_client):
        old = _sample_receipt(
            id="old",
            date=datetime(2026, 1, 1, 10, 0, 0),
        )
        new = _sample_receipt(
            id="new",
            date=datetime(2026, 3, 18, 19, 26, 50),
        )
        mock_client = MagicMock()
        mock_client.receipts.return_value = [old, new]
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["receipts", "--to", "2026-02-01", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "old"

    @patch("ilidl.cli._get_client")
    def test_receipts_store_falls_back_to_id(self, mock_get_client):
        receipt = _sample_receipt(
            store=Store(id="GB1459", name="", address="", postal_code="", locality=""),
        )
        mock_client = MagicMock()
        mock_client.receipts.return_value = [receipt]
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["receipts"])
        assert result.exit_code == 0
        assert "GB1459" in result.output


class TestCouponsCommand:
    @patch("ilidl.cli._get_client")
    def test_coupons_list_table(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.coupons.return_value = [_sample_coupon()]
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["coupons", "list"])
        assert result.exit_code == 0
        assert "Free Pizza" in result.output
        assert "2026-03-31" in result.output
        assert "No" in result.output

    @patch("ilidl.cli._get_client")
    def test_coupons_list_json(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.coupons.return_value = [_sample_coupon()]
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["coupons", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["title"] == "Free Pizza"

    @patch("ilidl.cli._get_client")
    def test_coupons_list_empty(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.coupons.return_value = []
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["coupons", "list"])
        assert result.exit_code == 0
        assert "No coupons available" in result.output

    @patch("ilidl.cli._get_client")
    def test_coupons_activate_by_id(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["coupons", "activate", "c1"])
        assert result.exit_code == 0
        assert "Coupon activated" in result.output
        mock_client.activate_coupon.assert_called_once_with("c1")

    @patch("ilidl.cli._get_client")
    def test_coupons_activate_no_id_no_all(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["coupons", "activate"])
        assert result.exit_code == 1
        assert "Provide a coupon ID" in result.output

    @patch("ilidl.cli._get_client")
    def test_coupons_activate_all(self, mock_get_client):
        inactive = _sample_coupon(id="c1", is_activated=False)
        active = _sample_coupon(id="c2", is_activated=True)
        mock_client = MagicMock()
        mock_client.coupons.return_value = [inactive, active]
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["coupons", "activate", "--all"])
        assert result.exit_code == 0
        assert "Activated" in result.output
        mock_client.activate_coupon.assert_called_once_with("c1")

    @patch("ilidl.cli._get_client")
    def test_coupons_activate_all_skips_on_error(self, mock_get_client):
        coupon = _sample_coupon(id="c1", is_activated=False)
        mock_client = MagicMock()
        mock_client.coupons.return_value = [coupon]
        error_resp = MagicMock(status_code=409)
        mock_client.activate_coupon.side_effect = requests.HTTPError(
            response=error_resp,
        )
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["coupons", "activate", "--all"])
        assert result.exit_code == 0
        assert "Skipped" in result.output

    @patch("ilidl.cli._get_client")
    def test_coupons_deactivate(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(cli, ["coupons", "deactivate", "c1"])
        assert result.exit_code == 0
        assert "Coupon deactivated" in result.output
        mock_client.deactivate_coupon.assert_called_once_with("c1")
