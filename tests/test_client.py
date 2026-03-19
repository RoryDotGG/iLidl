"""Tests for ilidl API client."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from ilidl.client import LidlClient
from ilidl.exceptions import AuthError, ILidlError
from ilidl.models import Receipt

FIXTURE = Path(__file__).parent / "fixtures" / "receipt_gb_sample.json"


def _mock_response(status_code: int = 200, json_data: dict | None = None, text: str = ""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _token_json(include_refresh: bool = True) -> dict:
    data = {"access_token": "test_access_token", "expires_in": 1200}
    if include_refresh:
        data["refresh_token"] = "new_refresh_token"
    return data


def _tickets_json(
    tickets: list | None = None,
    total_count: int | None = None,
    page_size: int = 25,
) -> dict:
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
    return {"page": 1, "size": page_size, "totalCount": total_count, "tickets": tickets}


def _detail_json() -> dict:
    return json.loads(FIXTURE.read_text())


def _make_client() -> LidlClient:
    client = LidlClient(
        refresh_token="test_refresh",
        country="GB",
        language="en",
    )
    client._http = MagicMock(spec=httpx.Client)
    return client


def _setup_token(client: LidlClient, include_refresh: bool = True) -> None:
    """Configure mock to return a valid token on the next POST call."""
    client._http.post.return_value = _mock_response(
        json_data=_token_json(include_refresh),
    )


class TestTokenRenewal:
    def test_renews_token_on_first_call(self):
        client = _make_client()
        _setup_token(client)
        headers = client._auth_headers()
        assert headers["Authorization"] == "Bearer test_access_token"
        client._http.post.assert_called_once()

    def test_reuses_token_when_not_expired(self):
        client = _make_client()
        _setup_token(client)
        client._auth_headers()
        client._auth_headers()
        assert client._http.post.call_count == 1

    def test_renewal_failure_raises_auth_error(self):
        client = _make_client()
        client._http.post.return_value = _mock_response(
            status_code=401,
            text="invalid_grant",
        )
        with pytest.raises(AuthError, match="Token renewal failed: 401"):
            client._auth_headers()

    def test_renewal_updates_refresh_token(self):
        client = _make_client()
        _setup_token(client, include_refresh=True)
        client._auth_headers()
        assert client._refresh_token == "new_refresh_token"

    def test_renewal_keeps_old_refresh_token_when_not_returned(self):
        client = _make_client()
        _setup_token(client, include_refresh=False)
        client._auth_headers()
        assert client._refresh_token == "test_refresh"

    def test_auth_headers_contain_required_fields(self):
        client = _make_client()
        _setup_token(client)
        headers = client._auth_headers()
        assert "Authorization" in headers
        assert headers["App-Version"] == "16.45.5"
        assert headers["Operating-System"] == "iOs"
        assert headers["Accept-Language"] == "en"

    def test_custom_app_version(self):
        client = LidlClient(
            refresh_token="test",
            country="GB",
            language="en",
            app_version="17.0.0",
        )
        client._http = MagicMock(spec=httpx.Client)
        _setup_token(client)
        headers = client._auth_headers()
        assert headers["App-Version"] == "17.0.0"


class TestGet:
    def test_get_passes_extra_headers(self):
        client = _make_client()
        _setup_token(client)
        client._http.get.return_value = _mock_response(json_data={"ok": True})
        client._get("https://example.com", extra_headers={"Country": "GB"})
        call_headers = client._http.get.call_args.kwargs["headers"]
        assert call_headers["Country"] == "GB"
        assert "Authorization" in call_headers

    def test_get_raises_on_http_error(self):
        client = _make_client()
        _setup_token(client)
        client._http.get.return_value = _mock_response(status_code=500)
        with pytest.raises(httpx.HTTPStatusError):
            client._get("https://example.com")


class TestReceipts:
    def test_latest_receipt(self):
        client = _make_client()
        _setup_token(client)
        client._http.get.side_effect = [
            _mock_response(json_data=_tickets_json()),
            _mock_response(json_data=_detail_json()),
        ]
        receipt = client.latest_receipt()
        assert isinstance(receipt, Receipt)
        assert receipt.total == 12.38
        assert len(receipt.items) == 7

    def test_latest_receipt_no_receipts_raises(self):
        client = _make_client()
        _setup_token(client)
        client._http.get.return_value = _mock_response(
            json_data=_tickets_json(tickets=[], total_count=0),
        )
        with pytest.raises(ILidlError, match="No receipts found"):
            client.latest_receipt()

    def test_receipt_by_id(self):
        client = _make_client()
        _setup_token(client)
        client._http.get.return_value = _mock_response(json_data=_detail_json())
        receipt = client.receipt("receipt123")
        assert receipt.id == "13001459742026031831079"
        assert receipt.store.name == "Llandaff"

    def test_receipts_single_page(self):
        client = _make_client()
        _setup_token(client)
        client._http.get.return_value = _mock_response(json_data=_tickets_json())
        result = client.receipts()
        assert len(result) == 1
        assert result[0].id == "receipt123"

    def test_receipts_pagination(self):
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
        page1 = _mock_response(
            json_data={
                "page": 1,
                "size": 2,
                "totalCount": 3,
                "tickets": [ticket_a, ticket_b],
            }
        )
        page2 = _mock_response(
            json_data={
                "page": 2,
                "size": 2,
                "totalCount": 3,
                "tickets": [ticket_c],
            }
        )
        client = _make_client()
        _setup_token(client)
        client._http.get.side_effect = [page1, page2]
        result = client.receipts()
        assert len(result) == 3
        assert [r.id for r in result] == ["a", "b", "c"]

    def test_receipts_only_favourite(self):
        client = _make_client()
        _setup_token(client)
        client._http.get.return_value = _mock_response(json_data=_tickets_json())
        client.receipts(only_favourite=True)
        url = client._http.get.call_args_list[0].args[0]
        assert "onlyFavorite=True" in url


class TestCoupons:
    def test_coupons_parses_sections(self):
        client = _make_client()
        _setup_token(client)
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
        client._http.get.return_value = _mock_response(json_data=coupon_data)
        coupons = client.coupons()
        assert len(coupons) == 1
        assert coupons[0].id == "c1"
        assert coupons[0].title == "Free Pizza"
        assert coupons[0].description == "50% off on all pizzas"
        assert coupons[0].image_url == "https://example.com/pizza.jpg"
        assert coupons[0].is_activated is True

    def test_coupons_empty_sections(self):
        client = _make_client()
        _setup_token(client)
        client._http.get.return_value = _mock_response(
            json_data={"sections": []},
        )
        assert client.coupons() == []

    def test_activate_coupon(self):
        client = _make_client()
        _setup_token(client)
        client._http.post.side_effect = [
            _mock_response(json_data=_token_json()),
            _mock_response(),
        ]
        client.activate_coupon("c1")
        assert client._http.post.call_count == 2
        activate_call = client._http.post.call_args_list[1]
        assert "c1/activation" in activate_call.args[0]
        assert activate_call.kwargs["headers"]["Country"] == "GB"

    def test_activate_coupon_http_error(self):
        client = _make_client()
        _setup_token(client)
        client._http.post.side_effect = [
            _mock_response(json_data=_token_json()),
            _mock_response(status_code=409),
        ]
        with pytest.raises(httpx.HTTPStatusError):
            client.activate_coupon("c1")

    def test_deactivate_coupon(self):
        client = _make_client()
        _setup_token(client)
        client._http.request.return_value = _mock_response()
        client.deactivate_coupon("c1")
        call_args = client._http.request.call_args
        assert call_args.args[0] == "DELETE"
        assert "c1/activation" in call_args.args[1]

    def test_deactivate_coupon_http_error(self):
        client = _make_client()
        _setup_token(client)
        client._http.request.return_value = _mock_response(status_code=404)
        with pytest.raises(httpx.HTTPStatusError):
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


class TestClientLifecycle:
    def test_context_manager(self):
        client = _make_client()
        with client:
            pass
        client._http.close.assert_called_once()

    def test_close(self):
        client = _make_client()
        client.close()
        client._http.close.assert_called_once()
