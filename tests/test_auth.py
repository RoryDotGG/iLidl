"""Tests for ilidl auth module."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from ilidl.auth import _build_auth_url, _exchange_code, _generate_pkce
from ilidl.exceptions import AuthError


class TestGeneratePkce:
    def test_returns_verifier_and_challenge(self):
        verifier, challenge = _generate_pkce()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)
        assert len(verifier) > 0
        assert len(challenge) > 0

    def test_challenge_differs_from_verifier(self):
        verifier, challenge = _generate_pkce()
        assert verifier != challenge

    def test_generates_unique_values(self):
        v1, _ = _generate_pkce()
        v2, _ = _generate_pkce()
        assert v1 != v2

    def test_challenge_is_base64url_without_padding(self):
        _, challenge = _generate_pkce()
        assert "+" not in challenge
        assert "/" not in challenge
        assert "=" not in challenge


class TestBuildAuthUrl:
    def test_contains_required_params(self):
        url = _build_auth_url("test_challenge", "gb", "en")
        assert "client_id=LidlPlusNativeClient" in url
        assert "response_type=code" in url
        assert "code_challenge=test_challenge" in url
        assert "code_challenge_method=S256" in url

    def test_uppercases_country(self):
        url = _build_auth_url("c", "gb", "en")
        assert "Country=GB" in url
        assert "language=en-GB" in url

    def test_encodes_redirect_uri(self):
        url = _build_auth_url("c", "gb", "en")
        assert "com.lidlplus.app%3A%2F%2Fcallback" in url

    def test_base_url(self):
        url = _build_auth_url("c", "gb", "en")
        assert url.startswith("https://accounts.lidl.com/connect/authorize?")


class TestExchangeCode:
    def test_returns_token_data(self):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
        }
        mock_resp.raise_for_status.return_value = None
        with patch("ilidl.auth.httpx.post", return_value=mock_resp):
            result = _exchange_code("code", "verifier")
        assert result["access_token"] == "at"
        assert result["refresh_token"] == "rt"

    def test_raises_auth_error_on_failure(self):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 400
        mock_resp.text = "invalid_grant"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400",
            request=MagicMock(),
            response=mock_resp,
        )
        with (
            patch("ilidl.auth.httpx.post", return_value=mock_resp),
            pytest.raises(AuthError, match="Token exchange failed: 400"),
        ):
            _exchange_code("code", "verifier")

    def test_sends_correct_payload(self):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "at"}
        mock_resp.raise_for_status.return_value = None
        with patch("ilidl.auth.httpx.post", return_value=mock_resp) as mock_post:
            _exchange_code("my_code", "my_verifier")
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["data"]["code"] == "my_code"
        assert call_kwargs["data"]["code_verifier"] == "my_verifier"
        assert call_kwargs["data"]["grant_type"] == "authorization_code"
