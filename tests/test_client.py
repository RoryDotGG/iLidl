"""Tests for ilidl API client, with lidl.co.uk replaced by an httpx.MockTransport."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from ilidl.client import LONDON, LidlClient
from ilidl.exceptions import AuthError, CouponError

HTML = (Path(__file__).parent / "fixtures" / "receipt_gb.html").read_text()
ACTIVATION = "/prm/api/v1/GB/promotions/c1/activation"


def _ticket(n: int) -> dict:
    return {
        "id": f"t{n}",
        "date": "2026-10-29T13:13:36+00:00",
        "totalAmount": 12.17,
        "articlesCount": 5,
        "store": "Testville",
        "isHtml": True,
    }


def _detail() -> dict:
    return {
        "ticket": {
            "id": "t1",
            "date": "2026-10-29T13:13:36",
            "totalAmount": 0,
            "store": {
                "id": None,
                "name": "Testville",
                "address": "1 High Street",
                "postalCode": "AB1 2CD",
                "locality": "Testford",
            },
            "htmlPrintedReceipt": HTML,
        },
        "coupons": [{"title": "15% off", "description": "15% off rice"}],
        "collectingModel": {"points": 13},
    }


def _promotion(**overrides) -> dict:
    p = {
        "id": "c1",
        "offer": "£5",
        "title": "off",
        "description": "£5 off when you spend £40",
        "image": {"url": "https://example.test/c1.png"},
        "isActivated": False,
        "isProcessing": False,
        "locked": False,
        "startValidityDate": "2026-10-26T06:32:38.02Z",
        "endValidityDate": "2026-11-01T23:59:59Z",
    }
    return {**p, **overrides}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> LidlClient:
    return LidlClient({"authToken": "x"}, transport=httpx.MockTransport(handler))


def _write_routes(requests: list[httpx.Request], activation: httpx.Response):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/mla/api/v1/token":
            return httpx.Response(200, json={"token": "jwt", "source": "3"})
        if request.url.path == "/prm/antiforgerytoken":
            return httpx.Response(200, headers={"set-cookie": "XSRF-TOKEN=csrf; path=/"})
        return activation

    return handler


def test_receipts_pages_until_total_count():
    pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        pages.append(page)
        items = [_ticket(n) for n in range(10)] if page == 1 else [_ticket(10)]
        return httpx.Response(
            200, json={"items": items, "page": page, "size": 10, "totalCount": 11}
        )

    receipts = list(_client(handler).receipts())
    assert pages == [1, 2]
    assert len(receipts) == 11
    assert receipts[0].total == Decimal("12.17")
    assert receipts[0].store.name == "Testville"
    assert receipts[0].date == datetime(2026, 10, 29, 13, 13, 36, tzinfo=LONDON)


def test_receipt_detail_uses_printed_total():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/mre/api/v1/tickets/t1"
        assert request.url.params["languageCode"] == "en-GB"
        return httpx.Response(200, json=_detail())

    receipt = _client(handler).receipt("t1")
    assert receipt.total == Decimal("4.00")
    assert len(receipt.items) == 4
    assert receipt.store.locality == "Testford"
    assert receipt.coupons_used == ["15% off"]
    assert receipt.points == 13
    assert receipt.date == datetime(2026, 10, 29, 13, 13, 36, tzinfo=LONDON)


def test_unauthorised_raises_auth_error():
    client = _client(lambda request: httpx.Response(401))
    with pytest.raises(AuthError, match="expired"):
        list(client.receipts())


def test_token_redirect_to_login_raises_auth_error():
    client = _client(lambda request: httpx.Response(302, headers={"location": "/login"}))
    with pytest.raises(AuthError):
        client.check_session()


def test_coupons_parse():
    client = _client(
        lambda request: httpx.Response(
            200, json={"sections": [{"id": "AllStores", "promotions": [_promotion(locked=True)]}]}
        )
    )
    [coupon] = client.coupons()
    assert coupon.description == "£5 off when you spend £40"
    assert coupon.is_locked and not coupon.is_activated
    assert coupon.start_date == datetime(2026, 10, 26, 6, 32, 38, 20000, tzinfo=UTC)
    assert coupon.image_url == "https://example.test/c1.png"


def test_activate_sends_bearer_and_csrf_and_reuses_them():
    requests: list[httpx.Request] = []
    client = _client(_write_routes(requests, httpx.Response(202)))

    client.activate_coupon("c1")
    client.deactivate_coupon("c1")

    writes = [r for r in requests if r.url.path == ACTIVATION]
    assert [r.method for r in writes] == ["POST", "DELETE"]
    for r in writes:
        assert r.headers["Authorization"] == "Bearer jwt"
        assert r.headers["X-CSRF-TOKEN"] == "csrf"
        assert r.url.params["language"] == "en-GB"
    assert sum(r.url.path == "/mla/api/v1/token" for r in requests) == 1


def test_activate_412_raises_coupon_error_with_reason():
    reason = "'StartValidityDate' must be less or equal than current date."
    client = _client(_write_routes([], httpx.Response(412, text=reason)))
    with pytest.raises(CouponError) as exc:
        client.activate_coupon("c1")
    assert exc.value.reason == reason


def test_missing_xsrf_cookie_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/mla/api/v1/token":
            return httpx.Response(200, json={"token": "jwt"})
        return httpx.Response(200)

    with pytest.raises(AuthError, match="XSRF"):
        _client(handler).activate_coupon("c1")


def test_receipt_dates_are_uk_local_time_despite_utc_label():
    ticket = {**_ticket(1), "date": "2026-05-17T13:15:48+00:00"}
    client = _client(
        lambda request: httpx.Response(
            200, json={"items": [ticket], "page": 1, "size": 10, "totalCount": 1}
        )
    )
    [receipt] = client.receipts()
    assert receipt.date.astimezone(UTC) == datetime(2026, 5, 17, 12, 15, 48, tzinfo=UTC)


def _expiring_site(accounts_logged_in: bool, visited: list[str]):
    """Fake lidl.co.uk whose session renews through accounts.lidl.com like the real site."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url
        visited.append(f"{url.host}{url.path}")
        fresh = "authToken=fresh" in request.headers.get("cookie", "")
        if url.host == "accounts.lidl.com":
            if not accounts_logged_in:
                return httpx.Response(200, text="<html>Log in</html>")
            return httpx.Response(
                302, headers={"location": "https://www.lidl.co.uk/user-api/signin-oidc?code=c"}
            )
        if url.path == "/user-api/login":
            return httpx.Response(
                302, headers={"location": "https://accounts.lidl.com/connect/authorize"}
            )
        if url.path == "/user-api/signin-oidc":
            return httpx.Response(
                302,
                headers={
                    "location": "/mla/api/v1/token?country_code=gb",
                    "set-cookie": "authToken=fresh; Path=/; Secure; HttpOnly",
                },
            )
        if url.path == "/mla/api/v1/token":
            if fresh:
                return httpx.Response(200, json={"token": "jwt", "source": "3"})
            return httpx.Response(302, headers={"location": "/user-api/login?step=login"})
        if url.path == "/mre/api/v1/tickets":
            if not fresh:
                return httpx.Response(401)
            return httpx.Response(200, json={"items": [], "page": 1, "size": 10, "totalCount": 0})
        return httpx.Response(404)

    return handler


def test_expired_session_renews_through_accounts_and_retries():
    visited: list[str] = []
    client = LidlClient(
        {"authToken": "stale"}, transport=httpx.MockTransport(_expiring_site(True, visited))
    )
    assert list(client.receipts()) == []
    assert "accounts.lidl.com/connect/authorize" in visited
    assert visited[-1] == "www.lidl.co.uk/mre/api/v1/tickets"


def test_expired_accounts_login_raises_auth_error():
    visited: list[str] = []
    client = LidlClient(
        {"authToken": "stale"}, transport=httpx.MockTransport(_expiring_site(False, visited))
    )
    with pytest.raises(AuthError, match="could not be renewed"):
        client.check_session()
    assert "accounts.lidl.com/connect/authorize" in visited
