"""Tests for ilidl doctor, with the browser and lidl.co.uk faked."""

import base64
import json
import time
from http.cookiejar import Cookie, CookieJar

import httpx
import pytest
from click.testing import CliRunner

from ilidl import doctor
from ilidl.cli import cli
from ilidl.client import LidlClient
from ilidl.exceptions import AuthError


def _jwt(expires_in: int) -> str:
    claims = json.dumps({"exp": int(time.time()) + expires_in}).encode()
    return f"h.{base64.urlsafe_b64encode(claims).decode().rstrip('=')}.s"


def _jar(token: str, accounts: bool = True) -> CookieJar:
    jar = CookieJar()
    hosts = [("www.lidl.co.uk", "authToken", token)]
    if accounts:
        hosts.append(("accounts.lidl.com", "idsrv", "x"))
    for domain, name, value in hosts:
        jar.set_cookie(
            Cookie(
                0,
                name,
                value,
                None,
                False,
                domain,
                False,
                False,
                "/",
                True,
                True,
                None,
                False,
                None,
                None,
                {},
            )
        )
    return jar


def _site(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/mla/api/v1/token":
        return httpx.Response(200, json={"token": "jwt"})
    if path == "/mre/api/v1/tickets":
        ticket = {
            "id": "t1",
            "date": "2026-10-29T13:13:36+00:00",
            "totalAmount": 12.17,
            "store": "Testville",
        }
        return httpx.Response(200, json={"items": [ticket], "page": 1, "size": 10, "totalCount": 1})
    if path == "/prm/api/v1/GB/promotionslist":
        return httpx.Response(200, json={"sections": []})
    return httpx.Response(404)


@pytest.fixture
def fake(monkeypatch):
    def use(jar, site=_site):
        monkeypatch.delenv("LIDL_COOKIE", raising=False)
        monkeypatch.setattr(doctor, "load_cookies", lambda browser: jar)
        monkeypatch.setattr(
            doctor,
            "LidlClient",
            lambda cookies: LidlClient(cookies, transport=httpx.MockTransport(site)),
        )
        return CliRunner().invoke(cli, ["doctor", "--browser", "brave"])

    return use


def test_healthy_setup_passes(fake):
    result = fake(_jar(_jwt(600)))
    assert result.exit_code == 0, result.output
    assert "min left" in result.output
    assert "Latest 29 Oct 2026, £12.17 at Testville" in result.output
    assert "0 available, 0 active" in result.output
    assert result.output.rstrip().endswith("All good.")


def test_expired_token_without_accounts_login_warns_then_fails(fake):
    result = fake(_jar(_jwt(-60), accounts=False), site=lambda request: httpx.Response(401))
    assert result.exit_code == 1
    assert "Expired at" in result.output
    assert "No accounts.lidl.com cookies" in result.output
    assert "could not be renewed" in result.output
    assert "Receipts" not in result.output


def test_unreadable_cookies_stop_with_the_fix(monkeypatch):
    def blocked(browser):
        raise AuthError("Could not read brave cookies. Add the terminal app under Full Disk Access")

    monkeypatch.delenv("LIDL_COOKIE", raising=False)
    monkeypatch.setattr(doctor, "load_cookies", blocked)
    result = CliRunner().invoke(cli, ["doctor", "--browser", "brave"])
    assert result.exit_code == 1
    assert "✗ Read cookies" in result.output
    assert "Full Disk Access" in result.output
    assert "Logged in" not in result.output


def test_auth_errors_point_to_doctor(monkeypatch):
    from unittest.mock import MagicMock, patch

    client = MagicMock()
    client.receipts.side_effect = AuthError("Lidl session expired and could not be renewed.")
    with patch("ilidl.cli._get_client", return_value=client):
        result = CliRunner().invoke(cli, ["receipts"])
    assert "Run `ilidl doctor`" in result.output


def test_expired_token_that_renews_is_not_a_warning(fake):
    result = fake(_jar(_jwt(-60)))
    assert result.exit_code == 0, result.output
    assert "✓ Session token" in result.output
    assert "Renewed and signed in" in result.output
    assert result.output.rstrip().endswith("All good.")
