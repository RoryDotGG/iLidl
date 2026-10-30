"""Tests for ilidl CLI, with the API client mocked."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ilidl.auth import load_cookies
from ilidl.cli import cli
from ilidl.exceptions import AuthError, CouponError
from ilidl.models import Coupon, Discount, Item, Receipt, Store


def _receipt(day: int, **overrides) -> Receipt:
    defaults = {
        "id": f"t{day}",
        "date": datetime(2026, 10, day, 13, 0, tzinfo=UTC),
        "store": Store(name="Testville", locality="Testford"),
        "total": Decimal("4.04"),
        "article_count": 4,
    }
    return Receipt(**{**defaults, **overrides})


def _coupon(coupon_id: str, **overrides) -> Coupon:
    defaults = {
        "id": coupon_id,
        "offer": "£5",
        "title": "off",
        "description": f"Coupon {coupon_id}",
        "start_date": datetime.now(UTC) - timedelta(days=1),
        "end_date": datetime.now(UTC) + timedelta(days=1),
        "is_activated": False,
    }
    return Coupon(**{**defaults, **overrides})


@pytest.fixture
def client():
    mock = MagicMock()
    with patch("ilidl.cli._get_client", return_value=mock):
        yield mock


def test_not_logged_in(monkeypatch):
    monkeypatch.delenv("LIDL_COOKIE", raising=False)
    with patch("ilidl.cli.Config") as config:
        config.return_value.browser = ""
        result = CliRunner().invoke(cli, ["receipts"])
    assert result.exit_code == 1
    assert "ilidl login --browser" in result.output


def test_auth_error_is_reported_without_traceback(client):
    client.receipts.side_effect = AuthError("Lidl session expired or missing.")
    result = CliRunner().invoke(cli, ["receipts"])
    assert result.exit_code == 1
    assert "Error: Lidl session expired" in result.output


def test_receipts_from_stops_paging_at_older_receipts(client):
    def newest_first():
        yield _receipt(29)
        yield _receipt(20)
        yield _receipt(10)
        raise AssertionError("fetched past --from")

    client.receipts.return_value = newest_first()
    result = CliRunner().invoke(cli, ["receipts", "--from", "2026-10-15", "--to", "2026-10-25"])
    assert result.exit_code == 0, result.output
    assert "t20" in result.output
    assert "t29" not in result.output


def test_receipt_json_serialises_decimals(client):
    client.receipt.return_value = _receipt(29)
    result = CliRunner().invoke(cli, ["receipt", "t29", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["total"] == 4.04
    client.receipt.assert_called_once_with("t29")


def test_receipt_table_shows_quantity_and_discount(client):
    item = Item(
        article_id="0080755",
        name="Sweet Potatoes",
        quantity=Decimal("0.692"),
        unit_price=Decimal("1.19"),
        price=Decimal("0.82"),
        vat_group="A",
        discounts=[Discount("p1", "15% off coupon", Decimal("0.12"))],
    )
    client.latest_receipt.return_value = _receipt(29, items=[item], payment_method="CARD")
    result = CliRunner().invoke(cli, ["receipt", "latest"])
    assert result.exit_code == 0
    assert "0.692" in result.output
    assert "15% off coupon" in result.output
    assert "-0.12" in result.output
    assert "Paid by: CARD" in result.output


def test_activate_all_skips_what_cannot_be_activated(client):
    later = datetime.now(UTC) + timedelta(hours=3)
    client.coupons.return_value = [
        _coupon("ok"),
        _coupon("active", is_activated=True),
        _coupon("locked", is_locked=True),
        _coupon("bakery", start_date=later),
        _coupon("refused"),
    ]

    def activate(coupon_id):
        if coupon_id == "refused":
            raise CouponError(coupon_id, "PromotionIsProcessing")

    client.activate_coupon.side_effect = activate
    result = CliRunner().invoke(cli, ["coupons", "activate", "--all"])

    assert result.exit_code == 0
    assert [c.args[0] for c in client.activate_coupon.call_args_list] == ["ok", "refused"]
    assert "Activated: Coupon ok" in result.output
    assert "Skipped: Coupon locked (locked)" in result.output
    assert f"Skipped: Coupon bakery (starts {later:%Y-%m-%d %H:%M} UTC)" in result.output
    assert "Skipped: Coupon refused (PromotionIsProcessing)" in result.output


def test_deactivate_reports_refusal_and_fails(client):
    client.deactivate_coupon.side_effect = [None, CouponError("b", "not active")]
    result = CliRunner().invoke(cli, ["coupons", "deactivate", "a", "b"])
    assert result.exit_code == 1
    assert "Deactivated: a" in result.output
    assert "Not deactivated: b (not active)" in result.output


def test_lidl_cookie_env_overrides_browser(monkeypatch):
    monkeypatch.setenv("LIDL_COOKIE", "authToken=abc; ldi-session-info=x=y")
    assert load_cookies("not-a-browser") == {"authToken": "abc", "ldi-session-info": "x=y"}


def test_unknown_browser(monkeypatch):
    monkeypatch.delenv("LIDL_COOKIE", raising=False)
    with pytest.raises(AuthError, match="Unknown browser"):
        load_cookies("netscape")


def test_unreadable_cookie_db_on_macos_explains_full_disk_access(monkeypatch):
    import browser_cookie3

    from ilidl import auth

    def blocked(domain_name):
        raise browser_cookie3.BrowserCookieError("Unable to read database file")

    monkeypatch.delenv("LIDL_COOKIE", raising=False)
    monkeypatch.setitem(auth.BROWSERS, "brave", blocked)
    monkeypatch.setattr(auth.sys, "platform", "darwin")
    with pytest.raises(AuthError, match="Full Disk Access.*LIDL_COOKIE"):
        load_cookies("brave")
