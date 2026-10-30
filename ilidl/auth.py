"""Load the lidl.co.uk session cookies from a logged-in browser."""

import os
import sys
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
        msg = f"Could not read {browser} cookies ({exc})."
        # browser_cookie3 hides the OS error, but on macOS this is almost always privacy
        # protection stopping the terminal from reading another app's data.
        if sys.platform == "darwin" and "database file" in str(exc):
            msg += (
                " macOS is probably blocking your terminal app from reading the browser's data:"
                " add the terminal app under System Settings > Privacy & Security >"
                " Full Disk Access, restart it and retry."
            )
        msg += f" Or set {COOKIE_ENV} instead."
        raise AuthError(msg) from exc
