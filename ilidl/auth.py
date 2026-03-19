"""Playwright-based OAuth2 PKCE authentication for Lidl Plus."""

import base64
import contextlib
import getpass
import hashlib
import re
import secrets

import requests

from ilidl.config import Config
from ilidl.exceptions import AuthError

AUTH_API = "https://accounts.lidl.com"
CLIENT_ID = "LidlPlusNativeClient"
REDIRECT_URI = "com.lidlplus.app://callback"
SCOPES = "openid profile offline_access lpprofile lpapis"


def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _build_auth_url(challenge: str, country: str, language: str) -> str:
    """Build the OAuth authorization URL."""
    params = (
        f"client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&scope={SCOPES.replace(' ', '+')}"
        f"&redirect_uri={REDIRECT_URI.replace(':', '%3A').replace('/', '%2F')}"
        f"&code_challenge={challenge}"
        f"&code_challenge_method=S256"
        f"&Country={country.upper()}"
        f"&language={language.lower()}-{country.upper()}"
    )
    return f"{AUTH_API}/connect/authorize?{params}"


def _exchange_code(code: str, verifier: str) -> dict:
    """Exchange authorization code for tokens."""
    secret = base64.b64encode(f"{CLIENT_ID}:secret".encode()).decode()
    resp = requests.post(
        f"{AUTH_API}/connect/token",
        headers={
            "Authorization": f"Basic {secret}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        msg = f"Token exchange failed: {resp.status_code} {resp.text}"
        raise AuthError(msg)
    return resp.json()


def _dbg(debug: bool, page, name: str, msg: str = ""):
    """Save a debug screenshot and optionally print a message."""
    if not debug:
        return
    page.screenshot(path=f"/tmp/ilidl_{name}.png")
    if msg:
        print(f"DEBUG {msg}")


def login(config: Config, *, debug: bool = False) -> str:
    """Run interactive login via phone number. Returns refresh token."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        msg = "Playwright is required for login. Install with: uv pip install 'ilidl[auth]'"
        raise AuthError(msg) from e

    verifier, challenge = _generate_pkce()
    url = _build_auth_url(challenge, config.country, config.language)

    phone = input("Phone number (local, e.g. 7400123456): ").strip()
    password = getpass.getpass("Password: ")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        code: str = ""

        def handle_request(request):
            nonlocal code
            req_url = request.url
            if debug:
                print(f"DEBUG request: {req_url[:120]}")
            if req_url.startswith("com.lidlplus.app://"):
                match = re.search(r"code=([^&]+)", req_url)
                if match:
                    code = match.group(1)
                    if debug:
                        print(f"DEBUG got code: {code}")

        def handle_response(response):
            nonlocal code
            # Check for 302 redirects to the app callback
            if code:
                return
            location = response.headers.get("location", "")
            if location.startswith("com.lidlplus.app://"):
                match = re.search(r"code=([^&]+)", location)
                if match:
                    code = match.group(1)
                    if debug:
                        print(f"DEBUG got code from redirect: {code}")

        page.on("request", handle_request)
        page.on("response", handle_response)

        page.goto(url)
        page.wait_for_load_state("networkidle")
        _dbg(debug, page, "01_welcome", f"url: {page.url}")

        # Click "Log in" on the welcome page
        page.locator("button:has-text('Log in'), a:has-text('Log in')").first.click(timeout=5000)
        page.wait_for_load_state("networkidle")
        _dbg(debug, page, "02_login_form", "on login form")

        # Switch to phone number login
        page.locator("button:has-text('phone number'), a:has-text('phone number')").first.click(
            timeout=5000
        )
        page.wait_for_load_state("networkidle")
        _dbg(debug, page, "03_phone_form", f"url: {page.url}")

        # Fill local phone number (country code is pre-selected)
        phone_field = page.locator(
            "input[type='tel'], input[name='PhoneNumber'], input[name='phoneNumber']"
        ).first
        phone_field.fill(phone)

        # Fill password
        page.locator("input[type='password']").first.fill(password)
        _dbg(debug, page, "04_filled")

        # Submit and wait for navigation or page change
        login_url = page.url
        page.locator("button:has-text('Log in'), button[type='submit']").first.click()

        # Wait for URL to change or for an error/verification
        # element to appear
        with contextlib.suppress(Exception):
            page.wait_for_function(
                f"window.location.href !== '{login_url}' || "
                "document.querySelector("
                '  \'[name="VerificationCode"],'
                "  .alert-danger,"
                "  .error-message'"
                ")",
                timeout=15000,
            )
        page.wait_for_load_state("networkidle")
        _dbg(debug, page, "05_after_submit", f"url: {page.url}")

        # Check for error message
        if not code:
            error_el = page.locator(
                ".alert-danger, .error-message, [class*='error'], [class*='Error']"
            )
            if error_el.first.is_visible(timeout=2000):
                error_text = error_el.first.text_content()
                _dbg(debug, page, "05b_error")
                browser.close()
                msg = f"Login failed: {error_text}"
                raise AuthError(msg)

        # Check for verification code prompt
        if not code:
            verify_field = page.locator(
                "[name='VerificationCode'], input[name='code'], input[inputmode='numeric']"
            )
            try:
                if verify_field.first.is_visible(timeout=10000):
                    _dbg(debug, page, "06_verify_prompt")
                    otp = input("Enter verification code: ").strip()
                    verify_field.first.fill(otp)
                    page.locator(
                        "button[type='submit'], "
                        "button:has-text('Submit'), "
                        "button:has-text('Verify')"
                    ).first.click()

                    # Wait for redirect after verify
                    with contextlib.suppress(Exception):
                        page.wait_for_url("**/callback*", timeout=15000)
                    page.wait_for_timeout(3000)
                    _dbg(debug, page, "07_after_verify", f"url: {page.url}")
            except Exception as exc:
                if debug:
                    print(f"DEBUG verify error: {exc}")
                _dbg(debug, page, "08_error")

        browser.close()

    if not code:
        msg = "Login failed: could not extract authorization code"
        raise AuthError(msg)

    tokens = _exchange_code(code, verifier)
    config.refresh_token = tokens["refresh_token"]
    config.save()
    return tokens["refresh_token"]
