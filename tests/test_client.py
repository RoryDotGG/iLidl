"""Tests for ilidl API client."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from ilidl.client import LidlClient
from ilidl.models import Receipt

FIXTURE = Path(__file__).parent / "fixtures" / "receipt_gb_sample.json"


def _mock_token_response():
    return MagicMock(
        status_code=200,
        json=lambda: {
            "access_token": "test_access_token",
            "expires_in": 1200,
            "refresh_token": "new_refresh_token",
        },
    )


def _mock_tickets_response():
    return MagicMock(
        status_code=200,
        json=lambda: {
            "page": 1,
            "size": 25,
            "totalCount": 1,
            "tickets": [
                {
                    "id": "receipt123",
                    "date": "2026-03-18T19:26:50+00:00",
                    "totalAmount": 12.38,
                    "currency": {"code": "GBP", "symbol": "£"},
                    "storeCode": "GB1459",
                    "articlesCount": 7,
                }
            ],
        },
    )


def _mock_ticket_detail_response():
    data = json.loads(FIXTURE.read_text())
    return MagicMock(status_code=200, json=lambda: data)


class TestTokenRenewal:
    @patch("ilidl.client.requests.post")
    def test_renews_token_on_first_call(self, mock_post):
        mock_post.return_value = _mock_token_response()
        client = LidlClient(
            refresh_token="test_refresh",
            country="GB",
            language="en",
        )
        headers = client._auth_headers()
        assert headers["Authorization"] == "Bearer test_access_token"
        mock_post.assert_called_once()

    @patch("ilidl.client.requests.post")
    def test_reuses_token_when_not_expired(self, mock_post):
        mock_post.return_value = _mock_token_response()
        client = LidlClient(
            refresh_token="test_refresh",
            country="GB",
            language="en",
        )
        client._auth_headers()
        client._auth_headers()
        assert mock_post.call_count == 1


class TestReceipts:
    @patch("ilidl.client.requests.get")
    @patch("ilidl.client.requests.post")
    def test_latest_receipt(self, mock_post, mock_get):
        mock_post.return_value = _mock_token_response()
        mock_get.side_effect = [
            _mock_tickets_response(),
            _mock_ticket_detail_response(),
        ]
        client = LidlClient(
            refresh_token="test_refresh",
            country="GB",
            language="en",
        )
        receipt = client.latest_receipt()
        assert isinstance(receipt, Receipt)
        assert receipt.total == 12.38
        assert len(receipt.items) == 7
