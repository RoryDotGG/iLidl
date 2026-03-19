"""Tests for ilidl API client."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from ilidl.client import LidlClient
from ilidl.exceptions import AuthError, ILidlError
from ilidl.models import Receipt

FIXTURE = Path(__file__).parent / "fixtures" / "receipt_gb_sample.json"


def _mock_token_response(include_refresh=True):
    data = {
        "access_token": "test_access_token",
        "expires_in": 1200,
    }
    if include_refresh:
        data["refresh_token"] = "new_refresh_token"
    return MagicMock(
        status_code=200,
        json=lambda: data,
    )


def _mock_tickets_response(tickets=None, total_count=None, page_size=25):
    if tickets is None:
        tickets = [
            {
                "id": "receipt123",
                "date": "2026-03-18T19:26:50+00:00",
                "totalAmount": 12.38,
                "currency": {"code": "GBP", "symbol": "\u00a3"},
                "storeCode": "GB1459",
                "articlesCount": 7,
            }
        ]
    if total_count is None:
        total_count = len(tickets)
    return MagicMock(
        status_code=200,
        json=lambda: {
            "page": 1,
            "size": page_size,
            "totalCount": total_count,
            "tickets": tickets,
        },
    )


def _mock_ticket_detail_response():
    data = json.loads(FIXTURE.read_text())
    return MagicMock(status_code=200, json=lambda: data)


def _make_client():
    return LidlClient(
        refresh_token="test_refresh",
        country="GB",
        language="en",
    )


class TestTokenRenewal:
    @patch("ilidl.client.requests.post")
    def test_renews_token_on_first_call(self, mock_post):
        mock_post.return_value = _mock_token_response()
        client = _make_client()
        headers = client._auth_headers()
        assert headers["Authorization"] == "Bearer test_access_token"
        mock_post.assert_called_once()

    @patch("ilidl.client.requests.post")
    def test_reuses_token_when_not_expired(self, mock_post):
        mock_post.return_value = _mock_token_response()
        client = _make_client()
        client._auth_headers()
        client._auth_headers()
        assert mock_post.call_count == 1

    @patch("ilidl.client.requests.post")
    def test_renewal_failure_raises_auth_error(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=401,
            text="invalid_grant",
        )
        client = _make_client()
        with pytest.raises(AuthError, match="Token renewal failed: 401"):
            client._auth_headers()

    @patch("ilidl.client.requests.post")
    def test_renewal_updates_refresh_token(self, mock_post):
        mock_post.return_value = _mock_token_response(include_refresh=True)
        client = _make_client()
        client._auth_headers()
        assert client._refresh_token == "new_refresh_token"

    @patch("ilidl.client.requests.post")
    def test_renewal_keeps_old_refresh_token_when_not_returned(self, mock_post):
        mock_post.return_value = _mock_token_response(include_refresh=False)
        client = _make_client()
        client._auth_headers()
        assert client._refresh_token == "test_refresh"

    @patch("ilidl.client.requests.post")
    def test_auth_headers_contain_required_fields(self, mock_post):
        mock_post.return_value = _mock_token_response()
        client = _make_client()
        headers = client._auth_headers()
        assert "Authorization" in headers
        assert headers["App-Version"] == "16.45.5"
        assert headers["Operating-System"] == "iOs"
        assert headers["Accept-Language"] == "en"


class TestGet:
    @patch("ilidl.client.requests.get")
    @patch("ilidl.client.requests.post")
    def test_get_passes_extra_headers(self, mock_post, mock_get):
        mock_post.return_value = _mock_token_response()
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"ok": True},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        client = _make_client()
        client._get("https://example.com", extra_headers={"Country": "GB"})
        call_headers = mock_get.call_args.kwargs["headers"]
        assert call_headers["Country"] == "GB"
        assert "Authorization" in call_headers

    @patch("ilidl.client.requests.get")
    @patch("ilidl.client.requests.post")
    def test_get_raises_on_http_error(self, mock_post, mock_get):
        mock_post.return_value = _mock_token_response()
        mock_get.return_value = MagicMock(status_code=500)
        mock_get.return_value.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        client = _make_client()
        with pytest.raises(requests.HTTPError):
            client._get("https://example.com")


class TestReceipts:
    @patch("ilidl.client.requests.get")
    @patch("ilidl.client.requests.post")
    def test_latest_receipt(self, mock_post, mock_get):
        mock_post.return_value = _mock_token_response()
        mock_get.side_effect = [
            _mock_tickets_response(),
            _mock_ticket_detail_response(),
        ]
        client = _make_client()
        receipt = client.latest_receipt()
        assert isinstance(receipt, Receipt)
        assert receipt.total == 12.38
        assert len(receipt.items) == 7

    @patch("ilidl.client.requests.get")
    @patch("ilidl.client.requests.post")
    def test_latest_receipt_no_receipts_raises(self, mock_post, mock_get):
        mock_post.return_value = _mock_token_response()
        mock_get.return_value = _mock_tickets_response(tickets=[], total_count=0)
        client = _make_client()
        with pytest.raises(ILidlError, match="No receipts found"):
            client.latest_receipt()

    @patch("ilidl.client.requests.get")
    @patch("ilidl.client.requests.post")
    def test_receipt_by_id(self, mock_post, mock_get):
        mock_post.return_value = _mock_token_response()
        mock_get.return_value = _mock_ticket_detail_response()
        client = _make_client()
        receipt = client.receipt("receipt123")
        assert receipt.id == "13001459742026031831079"
        assert receipt.store.name == "Llandaff"

    @patch("ilidl.client.requests.get")
    @patch("ilidl.client.requests.post")
    def test_receipts_single_page(self, mock_post, mock_get):
        mock_post.return_value = _mock_token_response()
        mock_get.return_value = _mock_tickets_response()
        client = _make_client()
        result = client.receipts()
        assert len(result) == 1
        assert result[0].id == "receipt123"

    @patch("ilidl.client.requests.get")
    @patch("ilidl.client.requests.post")
    def test_receipts_pagination(self, mock_post, mock_get):
        """Two pages: page 1 has 2 tickets, page 2 has 1 ticket."""
        ticket_a = {
            "id": "a",
            "date": "2026-03-18T10:00:00+00:00",
            "totalAmount": 5.00,
            "currency": {"code": "GBP"},
            "storeCode": "GB1",
        }
        ticket_b = {**ticket_a, "id": "b"}
        ticket_c = {**ticket_a, "id": "c"}
        page1 = MagicMock(
            status_code=200,
            json=lambda: {
                "page": 1,
                "size": 2,
                "totalCount": 3,
                "tickets": [ticket_a, ticket_b],
            },
        )
        page2 = MagicMock(
            status_code=200,
            json=lambda: {
                "page": 2,
                "size": 2,
                "totalCount": 3,
                "tickets": [ticket_c],
            },
        )
        mock_post.return_value = _mock_token_response()
        mock_get.side_effect = [page1, page2]
        client = _make_client()
        result = client.receipts()
        assert len(result) == 3
        assert [r.id for r in result] == ["a", "b", "c"]

    @patch("ilidl.client.requests.get")
    @patch("ilidl.client.requests.post")
    def test_receipts_only_favourite(self, mock_post, mock_get):
        mock_post.return_value = _mock_token_response()
        mock_get.return_value = _mock_tickets_response()
        client = _make_client()
        client.receipts(only_favourite=True)
        url = mock_get.call_args_list[0].args[0]
        assert "onlyFavorite=True" in url


class TestCoupons:
    @patch("ilidl.client.requests.get")
    @patch("ilidl.client.requests.post")
    def test_coupons_parses_sections(self, mock_post, mock_get):
        mock_post.return_value = _mock_token_response()
        coupon_data = {
            "sections": [
                {
                    "promotions": [
                        {
                            "id": "c1",
                            "title": "Free Pizza",
                            "validity": {
                                "start": "2026-03-01T00:00:00+00:00",
                                "end": "2026-03-31T23:59:59+00:00",
                            },
                            "discount": {
                                "title": "50% off",
                                "description": "on all pizzas",
                            },
                            "image": "https://example.com/pizza.jpg",
                            "isActivated": True,
                        }
                    ]
                }
            ]
        }
        resp = MagicMock(status_code=200, json=lambda: coupon_data)
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp
        client = _make_client()
        coupons = client.coupons()
        assert len(coupons) == 1
        assert coupons[0].id == "c1"
        assert coupons[0].title == "Free Pizza"
        assert coupons[0].description == "50% off on all pizzas"
        assert coupons[0].image_url == "https://example.com/pizza.jpg"
        assert coupons[0].is_activated is True

    @patch("ilidl.client.requests.get")
    @patch("ilidl.client.requests.post")
    def test_coupons_empty_sections(self, mock_post, mock_get):
        mock_post.return_value = _mock_token_response()
        resp = MagicMock(status_code=200, json=lambda: {"sections": []})
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp
        client = _make_client()
        assert client.coupons() == []

    @patch("ilidl.client.requests.post")
    def test_activate_coupon(self, mock_post):
        token_resp = _mock_token_response()
        activate_resp = MagicMock(status_code=200)
        activate_resp.raise_for_status = MagicMock()
        mock_post.side_effect = [token_resp, activate_resp]
        client = _make_client()
        client.activate_coupon("c1")
        assert mock_post.call_count == 2
        activate_call = mock_post.call_args_list[1]
        assert "c1/activation" in activate_call.args[0]
        assert activate_call.kwargs["headers"]["Country"] == "GB"

    @patch("ilidl.client.requests.post")
    def test_activate_coupon_http_error(self, mock_post):
        token_resp = _mock_token_response()
        error_resp = MagicMock(status_code=409)
        error_resp.raise_for_status.side_effect = requests.HTTPError("409 Conflict")
        mock_post.side_effect = [token_resp, error_resp]
        client = _make_client()
        with pytest.raises(requests.HTTPError):
            client.activate_coupon("c1")

    @patch("ilidl.client.requests.delete")
    @patch("ilidl.client.requests.post")
    def test_deactivate_coupon(self, mock_post, mock_delete):
        mock_post.return_value = _mock_token_response()
        mock_delete.return_value = MagicMock(status_code=200)
        mock_delete.return_value.raise_for_status = MagicMock()
        client = _make_client()
        client.deactivate_coupon("c1")
        assert "c1/activation" in mock_delete.call_args.args[0]

    @patch("ilidl.client.requests.delete")
    @patch("ilidl.client.requests.post")
    def test_deactivate_coupon_http_error(self, mock_post, mock_delete):
        mock_post.return_value = _mock_token_response()
        mock_delete.return_value = MagicMock(status_code=404)
        mock_delete.return_value.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        client = _make_client()
        with pytest.raises(requests.HTTPError):
            client.deactivate_coupon("c1")


class TestTicketConversion:
    def test_summary_to_receipt(self):
        ticket = {
            "id": "r1",
            "date": "2026-03-18T19:26:50+00:00",
            "totalAmount": 12.38,
            "currency": {"code": "GBP", "symbol": "\u00a3"},
            "storeCode": "GB1459",
        }
        receipt = LidlClient._ticket_summary_to_receipt(ticket)
        assert receipt.id == "r1"
        assert receipt.total == 12.38
        assert receipt.currency == "GBP"
        assert receipt.store.id == "GB1459"
        assert receipt.items == []

    def test_summary_missing_currency(self):
        ticket = {
            "id": "r1",
            "date": "2026-03-18T19:26:50+00:00",
            "totalAmount": 5.00,
        }
        receipt = LidlClient._ticket_summary_to_receipt(ticket)
        assert receipt.currency == ""

    def test_detail_to_receipt(self):
        data = json.loads(FIXTURE.read_text())
        receipt = LidlClient._ticket_detail_to_receipt(data)
        assert receipt.store.name == "Llandaff"
        assert receipt.store.locality == "Cardiff"
        assert len(receipt.items) == 7
        assert receipt.payment_method == "CARD"
        assert "A" in receipt.vat_breakdown
        assert "B" in receipt.vat_breakdown
