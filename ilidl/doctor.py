"""Checks behind ``ilidl doctor``. They report cookie names, hosts and times, never values."""

import base64
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from http.cookiejar import CookieJar

import httpx

from ilidl.auth import COOKIE_ENV, load_cookies
from ilidl.client import LidlClient
from ilidl.exceptions import AuthError, ILidlError

LOGIN_URL = "https://www.lidl.co.uk/mre/"


@dataclass
class Check:
    status: str
    """``ok``, ``warn`` or ``fail``. Checks stop after the first ``fail``."""
    title: str
    detail: str = ""
    fix: str = ""


def run(browser: str) -> Iterator[Check]:
    """Yield checks in order, from finding the cookies to calling the API."""
    from_env = bool(os.environ.get(COOKIE_ENV, "").strip())
    if from_env:
        yield Check(
            "warn",
            "Cookie source",
            f"{COOKIE_ENV} is set, so browser cookies are ignored",
            f"Unset {COOKIE_ENV} to use browser cookies, which can renew the session",
        )
    elif not browser:
        yield Check(
            "fail",
            "Cookie source",
            "No browser chosen",
            "Run: ilidl login --browser brave (or chrome, firefox, safari...)",
        )
        return
    else:
        yield Check("ok", "Cookie source", f"{browser} browser")

    try:
        cookies = load_cookies(browser)
    except AuthError as exc:
        yield Check("fail", "Read cookies", str(exc))
        return
    site, accounts = _split(cookies)
    yield Check("ok", "Read cookies", f"{len(site)} lidl.co.uk, {len(accounts)} accounts.lidl.com")

    token = site.get("authToken")
    if not token:
        yield Check(
            "fail",
            "Logged in to lidl.co.uk",
            "No authToken cookie",
            f"Log in at {LOGIN_URL} in {browser or 'your browser'}",
        )
        return
    yield Check("ok", "Logged in to lidl.co.uk", "authToken cookie found")

    expires = _jwt_expiry(token)
    expired = expires is not None and expires <= datetime.now().astimezone()
    if expires is None:
        yield Check("warn", "Session token", "authToken is not a JWT, so its expiry is unknown")
    elif expired:
        # Normal between browser visits: the token lasts 30 minutes and iLidl renews it.
        yield Check(
            "ok" if accounts else "warn",
            "Session token",
            f"Expired at {expires:%H:%M}, iLidl will renew it",
        )
    else:
        left = int((expires - datetime.now().astimezone()).total_seconds() // 60)
        yield Check("ok", "Session token", f"Valid until {expires:%H:%M} ({left} min left)")

    if accounts:
        yield Check("ok", "Renewal login", "accounts.lidl.com cookies found")
    else:
        yield Check(
            "warn",
            "Renewal login",
            f"No accounts.lidl.com cookies{' in ' + COOKIE_ENV if from_env else ''}, so the"
            " session stops working when the token expires",
            "" if from_env else f"Log in at {LOGIN_URL} in {browser}",
        )

    with LidlClient(cookies) as client:
        try:
            client.check_session()
        except AuthError as exc:
            yield Check("fail", "Lidl session", str(exc))
            return
        except httpx.HTTPError as exc:
            yield Check("fail", "Lidl session", f"Could not reach lidl.co.uk: {exc}")
            return
        yield Check("ok", "Lidl session", "Renewed and signed in" if expired else "Signed in")

        try:
            latest = next(client.receipts(), None)
        except (ILidlError, httpx.HTTPError) as exc:
            yield Check("fail", "Receipts", str(exc))
        else:
            if latest is None:
                yield Check("warn", "Receipts", "No receipts found")
            else:
                yield Check(
                    "ok",
                    "Receipts",
                    f"Latest {latest.date:%d %b %Y}, £{latest.total} at {latest.store.name}",
                )

        try:
            coupons = client.coupons()
        except (ILidlError, httpx.HTTPError) as exc:
            yield Check("fail", "Coupons", str(exc))
        else:
            active = sum(c.is_activated for c in coupons)
            yield Check("ok", "Coupons", f"{len(coupons)} available, {active} active")


def _split(cookies: CookieJar | dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Split cookies into lidl.co.uk and accounts.lidl.com name-to-value maps."""
    if isinstance(cookies, dict):
        return dict(cookies), {}
    site: dict[str, str] = {}
    accounts: dict[str, str] = {}
    for c in cookies:
        target = accounts if c.domain.lstrip(".").endswith("lidl.com") else site
        target[c.name] = c.value or ""
    return site, accounts


def _jwt_expiry(token: str) -> datetime | None:
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return datetime.fromtimestamp(int(claims["exp"])).astimezone()
    except (IndexError, KeyError, TypeError, ValueError):
        return None
