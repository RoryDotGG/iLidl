"""Playwright-based OAuth2 PKCE authentication for Lidl Plus."""

import base64
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


def login(config: Config) -> str:
    """Run interactive login flow. Returns refresh token."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        msg = "Playwright is required for login. Install with: uv pip install 'ilidl[auth]'"
        raise AuthError(msg) from e

    verifier, challenge = _generate_pkce()
    url = _build_auth_url(challenge, config.country, config.language)

    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        code: str = ""

        def handle_route(route):
            nonlocal code
            req_url = route.request.url
            if "callback?code=" in req_url:
                match = re.search(r"code=([0-9A-F]+)", req_url)
                if match:
                    code = match.group(1)
                route.abort()
            else:
                route.continue_()

        page.route("**/callback*", handle_route)
        page.goto(url)
        page.wait_for_load_state("networkidle")

        # Click "Log in" button on welcome page
        login_btn = page.locator("button:has-text('Log in')").first
        login_btn.click()
        page.wait_for_load_state("networkidle")

        # Fill email
        page.locator("#input-email").fill(email)
        # Fill password
        page.locator("input[id='Password'][type='password']").fill(password)

        # Submit
        page.locator("button:has-text('Log in')").first.click()

        # Wait for 2FA or redirect
        page.wait_for_timeout(3000)

        # Check for 2FA
        if not code:
            try:
                verify_field = page.locator("[name='VerificationCode']")
                if verify_field.is_visible(timeout=5000):
                    verify_code = input("Enter verification code: ").strip()
                    verify_field.fill(verify_code)
                    page.locator("button:has-text('Submit'), .role_next").first.click()
                    page.wait_for_timeout(3000)
            except Exception:
                pass

        browser.close()

    if not code:
        msg = "Login failed: could not extract authorization code"
        raise AuthError(msg)

    tokens = _exchange_code(code, verifier)
    config.refresh_token = tokens["refresh_token"]
    config.save()
    return tokens["refresh_token"]
