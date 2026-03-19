"""HTTP client for the Lidl Plus API."""

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ilidl.exceptions import AuthError, ILidlError
from ilidl.models import Coupon, Receipt, Store
from ilidl.parser import parse_receipt_html

DEFAULT_APP_VERSION = "16.45.5"
AUTH_API = "https://accounts.lidl.com"
TICKETS_API = "https://tickets.lidlplus.com/api"
COUPONS_API = "https://coupons.lidlplus.com/app/api"
CLIENT_ID = "LidlPlusNativeClient"


class _RetryTransport(httpx.BaseTransport):
    """Retries requests on connection errors."""

    def __init__(self, retries: int = 3) -> None:
        self._transport = httpx.HTTPTransport()
        self._retries = retries

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        last_exc: httpx.ConnectError | None = None
        for _ in range(self._retries):
            try:
                return self._transport.handle_request(request)
            except httpx.ConnectError as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        return self._transport.handle_request(request)

    def close(self) -> None:
        self._transport.close()


class LidlClient:
    """Client for the Lidl Plus API.

    Handles token renewal, receipt listing/detail, and coupons.
    """

    def __init__(
        self,
        refresh_token: str,
        country: str,
        language: str,
        app_version: str = DEFAULT_APP_VERSION,
    ) -> None:
        self._refresh_token = refresh_token
        self._country = country.upper()
        self._language = language.lower()
        self._app_version = app_version
        self._access_token: str = ""
        self._token_expires: datetime = datetime.min.replace(
            tzinfo=UTC,
        )
        self._http = httpx.Client(
            transport=_RetryTransport(retries=3),
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> "LidlClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _renew_token(self) -> None:
        secret = base64.b64encode(
            f"{CLIENT_ID}:secret".encode(),
        ).decode()
        resp = self._http.post(
            f"{AUTH_API}/connect/token",
            headers={
                "Authorization": f"Basic {secret}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            msg = f"Token renewal failed: {resp.status_code} {resp.text}"
            raise AuthError(msg) from exc
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires = datetime.now(
            tz=UTC,
        ) + timedelta(seconds=data["expires_in"])
        if "refresh_token" in data:
            self._refresh_token = data["refresh_token"]

    def _auth_headers(self) -> dict[str, str]:
        now = datetime.now(tz=UTC)
        if not self._access_token or now >= self._token_expires:
            self._renew_token()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "App-Version": self._app_version,
            "Operating-System": "iOs",
            "App": "com.lidl.eci.lidl.plus",
            "Accept-Language": self._language,
        }

    def _get(
        self,
        url: str,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = self._auth_headers()
        if extra_headers:
            headers.update(extra_headers)
        resp = self._http.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def receipts(
        self,
        only_favourite: bool = False,
    ) -> list[Receipt]:
        """Fetch all receipts, paginating automatically."""
        url = f"{TICKETS_API}/v2/{self._country}/tickets"
        first_page = self._get(
            f"{url}?pageNumber=1&onlyFavorite={only_favourite}",
        )
        tickets = first_page["tickets"]
        total_count = first_page["totalCount"]
        page_size = first_page["size"]
        for page in range(2, (total_count // page_size) + 2):
            page_data = self._get(
                f"{url}?pageNumber={page}&onlyFavorite={only_favourite}",
            )
            tickets.extend(page_data["tickets"])
        return [self._ticket_summary_to_receipt(t) for t in tickets]

    def receipt(self, ticket_id: str) -> Receipt:
        """Fetch a single receipt by ID with full detail."""
        url = f"{TICKETS_API}/v3/{self._country}/tickets/{ticket_id}"
        data = self._get(url)
        return self._ticket_detail_to_receipt(data)

    def latest_receipt(self) -> Receipt:
        """Fetch the most recent receipt with full detail."""
        url = f"{TICKETS_API}/v2/{self._country}/tickets"
        first_page = self._get(
            f"{url}?pageNumber=1&onlyFavorite=False",
        )
        tickets = first_page["tickets"]
        if not tickets:
            msg = "No receipts found"
            raise ILidlError(msg)
        return self.receipt(tickets[0]["id"])

    def _coupon_headers(self) -> dict[str, str]:
        return {"Country": self._country}

    def coupons(self) -> list[Coupon]:
        """Fetch all available coupons."""
        url = f"{COUPONS_API}/v2/promotionsList"
        data = self._get(url, self._coupon_headers())
        result: list[Coupon] = []
        for section in data.get("sections", []):
            for p in section.get("promotions", []):
                validity = p.get("validity", {})
                discount = p.get("discount", {})
                desc = discount.get("description", "")
                if discount.get("title"):
                    desc = f"{discount['title']} {desc}".strip()
                result.append(
                    Coupon(
                        id=p["id"],
                        title=p.get("title", ""),
                        description=desc,
                        image_url=p.get("image"),
                        start_date=datetime.fromisoformat(
                            validity["start"],
                        ),
                        end_date=datetime.fromisoformat(
                            validity["end"],
                        ),
                        is_activated=p.get("isActivated", False),
                    )
                )
        return result

    def activate_coupon(self, coupon_id: str) -> None:
        """Activate a coupon by ID."""
        url = f"{COUPONS_API}/v1/promotions/{coupon_id}/activation"
        headers = self._auth_headers()
        headers.update(self._coupon_headers())
        resp = self._http.post(url, headers=headers)
        resp.raise_for_status()

    def deactivate_coupon(self, coupon_id: str) -> None:
        """Deactivate a coupon by ID."""
        url = f"{COUPONS_API}/v2/promotions/{coupon_id}/activation"
        headers = self._auth_headers()
        headers.update(self._coupon_headers())
        resp = self._http.delete(url, headers=headers)
        resp.raise_for_status()

    @staticmethod
    def _ticket_summary_to_receipt(ticket: dict[str, Any]) -> Receipt:
        currency = ticket.get("currency", {})
        return Receipt(
            id=ticket["id"],
            date=datetime.fromisoformat(ticket["date"]),
            store=Store(
                id=ticket.get("storeCode", ""),
                name="",
                address="",
                postal_code="",
                locality="",
            ),
            items=[],
            total=ticket["totalAmount"],
            currency=currency.get("code", ""),
        )

    @staticmethod
    def _ticket_detail_to_receipt(data: dict[str, Any]) -> Receipt:
        store_data = data.get("store", {})
        store = Store(
            id=store_data.get("id", ""),
            name=store_data.get("name", ""),
            address=store_data.get("address", ""),
            postal_code=store_data.get("postalCode", ""),
            locality=store_data.get("locality", ""),
        )
        html = data.get("htmlPrintedReceipt", "")
        parsed = parse_receipt_html(html)
        return Receipt(
            id=data["id"],
            date=datetime.fromisoformat(data["date"]),
            store=store,
            items=parsed.items,
            total=parsed.total,
            currency=data.get("currency", {}).get("code", "GBP"),
            payment_method=parsed.payment_method,
            vat_breakdown=parsed.vat_breakdown,
        )
