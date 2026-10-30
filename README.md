# iLidl

Unofficial Python client and CLI for Lidl UK receipts and coupons. It uses the same API as the
lidl.co.uk website, authenticated by your logged-in browser session.

## Installation

```bash
pip install ilidl

# Or with uv
uv add ilidl
```

## Authentication

1. Log in at [lidl.co.uk](https://www.lidl.co.uk) in your browser.
2. Tell iLidl which browser to read the session from:

```bash
ilidl login --browser brave
```

This checks the session works and saves the browser name to `~/.config/ilidl/config.toml`.
Cookies are read from the browser on every run, so iLidl picks up the browser's refreshed session.
On macOS the first run asks for Keychain access to the browser's "Safe Storage" key. If it fails
with "Unable to read database file", macOS is blocking your terminal app from reading the
browser's data: add the terminal app under System Settings > Privacy & Security > Full Disk
Access, then restart it.

Supported browsers: `arc`, `brave`, `chrome`, `chromium`, `edge`, `firefox`, `librewolf`, `opera`,
`opera_gx`, `safari`, `vivaldi` (via [browser-cookie3](https://github.com/borisbabic/browser_cookie3)).

If the cookie store cannot be read, copy the cookies from DevTools instead. Open
[your receipts](https://www.lidl.co.uk/mre/), then in DevTools > Network pick a request to
`www.lidl.co.uk/mre/api/...` and copy its `Cookie` request header. `document.cookie` will not
work because the session cookie is HttpOnly.

```bash
export LIDL_COOKIE='authToken=...; ldi-session-info=...'
```

The session token (`authToken`) lasts 30 minutes. When it has expired, iLidl renews it the way the
website does, using your accounts.lidl.com login from the same browser. If that login has expired
too, commands fail with "Lidl session expired": log in at
[lidl.co.uk/mre](https://www.lidl.co.uk/mre/) in the browser and retry. A `LIDL_COOKIE` session
cannot be renewed, so it stops working after 30 minutes.

## CLI usage

```bash
# Receipts (newest first)
ilidl receipts                      # all receipts
ilidl receipts --limit 10
ilidl receipts --from 2026-10-01 --to 2026-10-31
ilidl receipt latest                # most recent receipt with line items
ilidl receipt <id>

# Coupons
ilidl coupons list
ilidl coupons activate <id> [<id>...]
ilidl coupons activate --all        # every inactive coupon that can be activated now
ilidl coupons deactivate <id> [<id>...]
```

`receipts`, `receipt` and `coupons list` support `--json`.

`coupons activate --all` re-lists coupons first. Time-slot coupons, such as the bakery 20% coupon,
get a new ID for each slot, and coupons that have not started yet are skipped.

## Library usage

```python
from ilidl import LidlClient
from ilidl.auth import load_cookies

with LidlClient(load_cookies("brave")) as client:
    receipt = client.latest_receipt()
    for item in receipt.items:
        print(item.name, item.quantity, item.price)
        for discount in item.discounts:
            print("  ", discount.description, -discount.amount)

    for coupon in client.coupons():
        if not coupon.is_activated:
            client.activate_coupon(coupon.id)  # raises CouponError if Lidl refuses
```

Money values are `Decimal`. `client.receipts()` yields receipt summaries (no line items) and fetches
pages lazily; `client.receipt(id)` fetches the line items.

## Notes

- Only Lidl UK (`www.lidl.co.uk`) is supported.
- Line items come from the receipt's printed HTML, which tags each line with `data-*` attributes.
  See [docs/lidl-web-api.md](docs/lidl-web-api.md) for the endpoints and markup.
- The API is undocumented and may change without notice.
