"""HTTP client for the Lidl UK web API (www.lidl.co.uk)."""

import time
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from http.cookiejar import CookieJar
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ilidl.exceptions import AuthError, CouponError, ILidlError, ReceiptParseError
from ilidl.models import Coupon, Receipt, Store
from ilidl.parser import parse_receipt_html

BASE_URL = "https://www.lidl.co.uk"
COUNTRY = "GB"
LANGUAGE = "en-GB"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
LONDON = ZoneInfo("Europe/London")
# The bearer token lasts 30 minutes; renew a little early.
_TOKEN_TTL_SECONDS = 25 * 60


class _RetryTransport(httpx.BaseTransport):
    """Retries requests on connection errors, which happen before anything is sent."""

    def __init__(self, retries: int = 3) -> None:
        self._transport = httpx.HTTPTransport()
        self._retries = retries

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for attempt in range(self._retries):
            try:
                return self._transport.handle_request(request)
            except httpx.ConnectError:
                if attempt == self._retries - 1:
                    raise
        raise AssertionError("unreachable")

    def close(self) -> None:
        self._transport.close()


class LidlClient:
    """Client for the Lidl UK web API, authenticated by the website's session cookies.

    Reads need only the cookies. Coupon changes also need a bearer token from
    ``/mla/api/v1/token`` and an ``X-CSRF-TOKEN`` header echoing the ``XSRF-TOKEN`` cookie
    set by ``/prm/antiforgerytoken``; both are fetched on demand.
    """

    def __init__(
        self,
        cookies: CookieJar | dict[str, str],
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=BASE_URL,
            cookies=cookies,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            transport=transport or _RetryTransport(),
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        self._write_headers: dict[str, str] = {}
        self._write_headers_expire = 0.0

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> "LidlClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        resp = self._http.request(method, path, **kwargs)
        # An expired session gives 401 on API calls and a redirect to the login page on /mla.
        if resp.status_code == 401 or resp.is_redirect:
            msg = (
                "Lidl session expired or missing. The session token lasts 30 minutes and the"
                " browser only renews it while lidl.co.uk is open: open https://www.lidl.co.uk/mre/"
                " in your browser (log in if asked) and retry."
            )
            raise AuthError(msg)
        return resp

    def _get(self, path: str, **params: Any) -> Any:
        resp = self._request("GET", path, params=params)
        resp.raise_for_status()
        return resp.json()

    def check_session(self) -> None:
        """Raise ``AuthError`` unless the cookies hold a live session."""
        self._get("/mla/api/v1/token")

    # Receipts

    def receipts(self) -> Iterator[Receipt]:
        """Yield receipt summaries, newest first, fetching 10 per page as needed."""
        page = 1
        while True:
            data = self._get("/mre/api/v1/tickets", country=COUNTRY, page=page)
            for ticket in data["items"]:
                yield Receipt(
                    id=ticket["id"],
                    date=_receipt_date(ticket["date"]),
                    store=Store(name=ticket.get("store") or ""),
                    total=Decimal(str(ticket["totalAmount"])),
                    article_count=ticket.get("articlesCount"),
                )
            if not data["items"] or page * data["size"] >= data["totalCount"]:
                return
            page += 1

    def receipt(self, ticket_id: str) -> Receipt:
        """Fetch a single receipt with its line items."""
        data = self._get(f"/mre/api/v1/tickets/{ticket_id}", country=COUNTRY, languageCode=LANGUAGE)
        ticket = data["ticket"]
        html = ticket.get("htmlPrintedReceipt") or ""
        if not html:
            msg = f"Receipt {ticket_id} has no printed receipt to parse"
            raise ReceiptParseError(msg, html)
        parsed = parse_receipt_html(html)
        store = ticket.get("store") or {}
        return Receipt(
            id=ticket["id"],
            date=_receipt_date(ticket["date"]),
            store=Store(
                name=store.get("name") or "",
                address=store.get("address") or "",
                postal_code=store.get("postalCode") or "",
                locality=store.get("locality") or "",
            ),
            # ticket.totalAmount is always 0 here; the printed receipt has the real total.
            total=parsed.total,
            article_count=len(parsed.items),
            items=parsed.items,
            payment_method=parsed.payment_method,
            vat_breakdown=parsed.vat_breakdown,
            coupons_used=[c.get("title") or "" for c in data.get("coupons") or []],
            points=(data.get("collectingModel") or {}).get("points"),
        )

    def latest_receipt(self) -> Receipt:
        """Fetch the most recent receipt with its line items."""
        latest = next(self.receipts(), None)
        if latest is None:
            msg = "No receipts found"
            raise ILidlError(msg)
        return self.receipt(latest.id)

    # Coupons

    def coupons(self) -> list[Coupon]:
        """Fetch all coupons.

        Time-slot coupons (such as the bakery 20% coupon) get a new ID for each slot, so
        re-list before activating rather than reusing old IDs.
        """
        data = self._get(f"/prm/api/v1/{COUNTRY}/promotionslist", language=LANGUAGE)
        return [
            Coupon(
                id=p["id"],
                offer=p.get("offer") or "",
                title=p.get("title") or "",
                description=p.get("description") or "",
                start_date=datetime.fromisoformat(p["startValidityDate"]),
                end_date=datetime.fromisoformat(p["endValidityDate"]),
                is_activated=bool(p.get("isActivated")),
                is_locked=bool(p.get("locked")),
                is_processing=bool(p.get("isProcessing")),
                image_url=(p.get("image") or {}).get("url"),
            )
            for section in data.get("sections") or []
            for p in section.get("promotions") or []
        ]

    def activate_coupon(self, coupon_id: str) -> None:
        """Activate a coupon. Raises ``CouponError`` if Lidl refuses."""
        self._set_activation(coupon_id, "POST")

    def deactivate_coupon(self, coupon_id: str) -> None:
        """Deactivate a coupon. Raises ``CouponError`` if Lidl refuses."""
        self._set_activation(coupon_id, "DELETE")

    def _set_activation(self, coupon_id: str, method: str) -> None:
        resp = self._request(
            method,
            f"/prm/api/v1/{COUNTRY}/promotions/{coupon_id}/activation",
            params={"language": LANGUAGE},
            headers=self._get_write_headers(),
        )
        # 412 is a business error with a plain-text reason, e.g. PromotionIsProcessing or
        # "'StartValidityDate' must be less or equal than current date."
        if resp.status_code == 412:
            raise CouponError(coupon_id, resp.text.strip() or "refused")
        resp.raise_for_status()

    def _get_write_headers(self) -> dict[str, str]:
        if time.monotonic() < self._write_headers_expire:
            return self._write_headers
        token = self._get("/mla/api/v1/token")["token"]
        auth = {"Authorization": f"Bearer {token}"}
        resp = self._request("GET", "/prm/antiforgerytoken", headers=auth)
        resp.raise_for_status()
        xsrf = resp.cookies.get("XSRF-TOKEN") or next(
            (c.value for c in self._http.cookies.jar if c.name == "XSRF-TOKEN"), None
        )
        if not xsrf:
            msg = "Lidl did not return an XSRF-TOKEN cookie"
            raise AuthError(msg)
        self._write_headers = {**auth, "X-CSRF-TOKEN": xsrf}
        self._write_headers_expire = time.monotonic() + _TOKEN_TTL_SECONDS
        return self._write_headers


def _receipt_date(value: str) -> datetime:
    # Receipt times are UK wall-clock time, matching the till printout, even when the API
    # labels them +00:00 during British Summer Time.
    return datetime.fromisoformat(value).replace(tzinfo=LONDON)
