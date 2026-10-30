# Lidl UK web API

Observed on www.lidl.co.uk on 2026-10-30. Undocumented and subject to change.

Each feature of the website is a separate app with its own backend under
`https://www.lidl.co.uk/<app>/`: `mla` (account), `mre` (receipts), `prm` (coupons) and `ben`
(partner benefits).

## Authentication

| Piece | Source | Needed for |
|---|---|---|
| `authToken`, `ldi-session-info` cookies | Logging in on the website (HttpOnly) | Everything. Reads need only these |
| Bearer JWT | `GET /mla/api/v1/token` returns `{token, source}`. Issued by accounts.lidl.com, lasts 30 minutes | Coupon changes |
| `X-CSRF-TOKEN` header | Value of the `XSRF-TOKEN` cookie set by `GET /prm/antiforgerytoken` (send the bearer token) | Coupon changes |

Without a valid session, API calls return 401 and `/mla/api/v1/token` redirects to the login page.

## Receipts (`/mre`)

`GET /mre/api/v1/tickets?country=GB&page=N` lists receipts, newest first, 10 per page:

```
{items: [{id, date, store, totalAmount, articlesCount, isHtml, vendor,
          badges: {coupons, returns, invoice, isAvailable}}],
 page, size, totalCount}
```

`store` is the store name as a string. `date` is labelled `+00:00` but is UK wall-clock time:
a receipt printed at 13:15 BST in May has `13:15:48+00:00`. A page past the end
returns an empty `items` list.

`GET /mre/api/v1/tickets/{id}?country=GB&languageCode=en-GB` returns one receipt:

```
{ticket: {id, date, store: {name, address, postalCode, locality}, codes, htmlPrintedReceipt,
          totalAmount},
 coupons: [{title, description}], collectingModel: {points, pointsDate}, returnTickets, ...}
```

`ticket.date` has no offset and is the same UK wall-clock time as the list. `ticket.totalAmount` is always 0;
use the list's `totalAmount` or the TOTAL line of the printed receipt.

### Printed receipt markup

Line items exist only in `htmlPrintedReceipt`, tagged with data attributes:

| Span | Attributes and content |
|---|---|
| `span.article` | `data-art-id`, `data-art-description`, `data-unit-price`, `data-tax-type`, `data-art-quantity` (a count, or kg for weighed goods; absent means 1) |
| `span.discount` | `data-promotion-id`. Several spans share one line `id`: the label ("15% off coupon") comes before the amount ("-0.16"). Applies to the article above |
| `span[id^=purchase_list_line]` with only `css_bold` | Older receipts' discount lines: a label ("Price Cut") then the amount ("-0.04"), with no promotion ID |
| `span[id^=purchase_summary]` | The `TOTAL` label followed by the total |
| `span[data-tender-description]` | Payment type, e.g. `CARD` |
| `span[id^=vat_info_line]` | `data-tax-type`, `data-tax-percentage`, `data-tax-base-amount` (gross), `data-tax-amount` |

Weighed goods repeat the article span on a second "0.692 kg @ £1.19/kg" line. That span may or
may not share the item line's `id`, so skip article spans whose text is a weight line rather than
deduplicating by `id`.

The line total is `quantity * unit price` rounded to the penny. Across 459 real receipts
(Nov 2024 to Oct 2026), line totals less discounts equal the list's `totalAmount` for every one.

Receipts are fixed-width text and long lines are cut off. An item line can lose its VAT letter,
and one receipt's TOTAL prints as `6.1` for 6.16. Take amounts from the data attributes, not the
text.

## Coupons (`/prm`)

- `GET /prm/api/v1/GB/promotionslist?language=en-GB` returns
  `{activatedCount, navigation, sections: [{id, promotions: [...]}]}`. Each promotion has `id`,
  `offer` ("£5"), `title` ("off"), `description` ("£5 off when you spend £40"), `image.url`,
  `isActivated`, `isProcessing`, `locked`, `startValidityDate`, `endValidityDate` (UTC),
  `channel`, `articleIds` and more.
- `GET /prm/api/v1/GB/promotions/{id}?language=en-GB` returns one promotion with its
  `conditions`, `products` and `stores`.
- Activate: `POST /prm/api/v1/GB/promotions/{id}/activation?language=en-GB` with no body, the
  bearer token and `X-CSRF-TOKEN`. Returns 202 with an empty body.
- Deactivate: `DELETE` on the same URL. Returns 202.
- 412 is a business error with a plain-text reason, for example `PromotionIsProcessing`,
  `UserPromotionIsCheckedOut`, an already active coupon, or
  `'StartValidityDate' must be less or equal than current date.`

Time-slot coupons, such as the bakery 20% coupon, get a new ID for each slot, so list coupons
again before activating.

## Other endpoints

Not used by iLidl:

- `GET /mla/api/v2/profile?client_id=greatbritainretailclient&country_code=gb&language=en-GB`
- `GET /mla/api/v1/points?country_code=gb`
- `GET /ben/api/v1/benefits?country=GB&languageCode=en-GB` (partner offers)
