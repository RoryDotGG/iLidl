"""Load the lidl.co.uk session cookies from a logged-in browser."""

import os
from http.cookiejar import CookieJar

import browser_cookie3

from ilidl.exceptions import AuthError

BROWSERS = {fn.__name__: fn for fn in browser_cookie3.all_browsers}
COOKIE_ENV = "LIDL_COOKIE"


def load_cookies(browser: str) -> CookieJar | dict[str, str]:
    """Return lidl.co.uk cookies.

    ``LIDL_COOKIE`` (a ``Cookie`` header copied from the browser's DevTools) wins over the
    browser's cookie store.

    Raises:
        AuthError: If the browser is unknown or its cookie store cannot be read.
    """
    if raw := os.environ.get(COOKIE_ENV, "").strip():
        pairs = (part.strip().split("=", 1) for part in raw.split(";") if "=" in part)
        return {name: value for name, value in pairs}
    if browser not in BROWSERS:
        msg = f"Unknown browser {browser!r}. Choose one of: {', '.join(BROWSERS)}"
        raise AuthError(msg)
    try:
        return BROWSERS[browser](domain_name="lidl.co.uk")
    except browser_cookie3.BrowserCookieError as exc:
        msg = f"Could not read {browser} cookies ({exc}). Set {COOKIE_ENV} instead."
        raise AuthError(msg) from exc
