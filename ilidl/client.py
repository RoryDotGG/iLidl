"""HTTP client for the Lidl Plus API."""

import base64
from datetime import UTC, datetime, timedelta

import requests

from ilidl.exceptions import AuthError, ILidlError
from ilidl.models import Coupon, Receipt, Store
from ilidl.parser import parse_receipt_html

APP_VERSION = "16.45.5"
AUTH_API = "https://accounts.lidl.com"
TICKETS_API = "https://tickets.lidlplus.com/api"
COUPONS_API = "https://coupons.lidlplus.com/api"
CLIENT_ID = "LidlPlusNativeClient"
TIMEOUT = 30


class LidlClient:
    """Client for the Lidl Plus API.

    Handles token renewal, receipt listing/detail, and coupons.
    """

    def __init__(
        self,
        refresh_token: str,
        country: str,
        language: str,
    ) -> None:
        self._refresh_token = refresh_token
        self._country = country.upper()
        self._language = language.lower()
        self._access_token: str = ""
        self._token_expires: datetime = datetime.min.replace(
            tzinfo=UTC,
        )

    def _renew_token(self) -> None:
        secret = base64.b64encode(
            f"{CLIENT_ID}:secret".encode(),
        ).decode()
        resp = requests.post(
            f"{AUTH_API}/connect/token",
            headers={
                "Authorization": f"Basic {secret}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            msg = (
                f"Token renewal failed: {resp.status_code} {resp.text}"
            )
            raise AuthError(msg)
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
            "App-Version": APP_VERSION,
            "Operating-System": "iOs",
            "App": "com.lidl.eci.lidl.plus",
            "Accept-Language": self._language,
        }

    def _get(self, url: str) -> dict:
        resp = requests.get(
            url,
            headers=self._auth_headers(),
            timeout=TIMEOUT,
        )
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
                f"{url}?pageNumber={page}"
                f"&onlyFavorite={only_favourite}",
            )
            tickets.extend(page_data["tickets"])
        return [self._ticket_summary_to_receipt(t) for t in tickets]

    def receipt(self, ticket_id: str) -> Receipt:
        """Fetch a single receipt by ID with full detail."""
        url = (
            f"{TICKETS_API}/v3/{self._country}/tickets/{ticket_id}"
        )
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

    def coupons(self) -> list[Coupon]:
        """Fetch all available coupons."""
        url = f"{COUPONS_API}/v2/{self._country}"
        data = self._get(url)
        result: list[Coupon] = []
        for section in data.get("sections", []):
            for c in section.get("coupons", []):
                result.append(
                    Coupon(
                        id=c["id"],
                        title=c.get("title", ""),
                        description=c.get(
                            "offerDescriptionShort", "",
                        ),
                        image_url=c.get("image"),
                        start_date=datetime.fromisoformat(
                            c["startValidityDate"],
                        ),
                        end_date=datetime.fromisoformat(
                            c["endValidityDate"],
                        ),
                        is_activated=c.get("isActivated", False),
                    )
                )
        return result

    def activate_coupon(self, coupon_id: str) -> None:
        """Activate a coupon by ID."""
        url = (
            f"{COUPONS_API}/v1/{self._country}"
            f"/{coupon_id}/activation"
        )
        resp = requests.post(
            url,
            headers=self._auth_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()

    def deactivate_coupon(self, coupon_id: str) -> None:
        """Deactivate a coupon by ID."""
        url = (
            f"{COUPONS_API}/v1/{self._country}"
            f"/{coupon_id}/activation"
        )
        resp = requests.delete(
            url,
            headers=self._auth_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()

    @staticmethod
    def _ticket_summary_to_receipt(ticket: dict) -> Receipt:
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
    def _ticket_detail_to_receipt(data: dict) -> Receipt:
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
