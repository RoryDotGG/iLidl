"""Parse UK Lidl HTML receipts into structured data.

Line items exist only inside the receipt's ``htmlPrintedReceipt``, tagged with data attributes:

- ``span.article``: ``data-art-id``, ``data-art-description``, ``data-unit-price``,
  ``data-tax-type`` and ``data-art-quantity`` (a count, or kg for weighed goods; absent means 1).
  Weighed goods repeat the span on a second "0.692 kg @ £1.19/kg" line, sometimes with the
  same ``id`` and sometimes not, so those lines are skipped by their text.
- ``span.discount``: ``data-promotion-id``. Spans sharing one line hold the label
  ("15% off coupon") then the amount ("-0.16"), and apply to the article above.
  Older receipts mark discount lines with only ``css_bold`` ("Price Cut", "-0.04"), so any
  negative amount on a non-article purchase line counts as a discount.
- ``span[id^=vat_info_line]``: ``data-tax-type``, ``data-tax-base-amount``, ``data-tax-amount``.
- ``span[data-tender-description]``: payment type, e.g. ``CARD``.

Receipts are fixed-width text, and long lines are cut off: an item line can lose its VAT letter
and the TOTAL can print as "6.1" for 6.16. Amounts therefore come from the data attributes, and a
cut-off TOTAL falls back to the sum of the lines less discounts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from html.parser import HTMLParser

from ilidl.exceptions import ReceiptParseError
from ilidl.models import Discount, Item

_AMOUNT = re.compile(r"-?\d+\.\d{2}")
_WEIGHT_LINE = re.compile(r"[\d.]+\s*kg\s*@")
_PENNY = Decimal("0.01")


@dataclass
class ParsedReceipt:
    """Result from HTML receipt parsing."""

    items: list[Item]
    total: Decimal
    payment_method: str | None = None
    vat_breakdown: dict[str, tuple[Decimal, Decimal]] = field(default_factory=dict)


class _ReceiptHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[Item] = []
        self.total: Decimal | None = None
        self.payment_method: str | None = None
        self.vat: dict[str, tuple[Decimal, Decimal]] = {}
        self._span: dict[str, str | None] | None = None
        self._label = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "span":
            return
        a = dict(attrs)
        self._span = a
        span_id = a.get("id") or ""
        if a.get("data-tender-description"):
            self.payment_method = a["data-tender-description"]
        if span_id.startswith("vat_info_line") and a.get("data-tax-type"):
            self.vat[a["data-tax-type"] or ""] = (
                Decimal(a.get("data-tax-base-amount") or "0"),
                Decimal(a.get("data-tax-amount") or "0"),
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            self._span = None

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if self._span is None or not text:
            return
        span_id = self._span.get("id") or ""
        classes = (self._span.get("class") or "").split()

        if "article" in classes and "data-art-description" in self._span:
            if not _WEIGHT_LINE.match(text):
                self.items.append(_item(self._span))
            self._span = None
        elif "currency" in classes:
            return
        elif span_id.startswith("purchase_list_line") and self.items:
            if text.startswith("-") and _AMOUNT.fullmatch(text):
                self.items[-1].discounts.append(
                    Discount(
                        promotion_id=self._span.get("data-promotion-id") or "",
                        description=self._label,
                        amount=-Decimal(text),
                    )
                )
                self._label = ""
            elif not _AMOUNT.fullmatch(text):
                self._label = text
        elif span_id.startswith("purchase_summary"):
            if text == "TOTAL":
                self._label = "TOTAL"
            elif self._label == "TOTAL":
                self.total = Decimal(text) if _AMOUNT.fullmatch(text) else None
                self._label = ""


def _item(a: dict[str, str | None]) -> Item:
    quantity = Decimal(a.get("data-art-quantity") or "1")
    unit_price = Decimal(a.get("data-unit-price") or "0")
    return Item(
        article_id=a.get("data-art-id") or "",
        name=a.get("data-art-description") or "",
        quantity=quantity,
        unit_price=unit_price,
        price=(quantity * unit_price).quantize(_PENNY, ROUND_HALF_UP),
        vat_group=a.get("data-tax-type") or "",
    )


def parse_receipt_html(html: str) -> ParsedReceipt:
    """Parse a UK Lidl receipt HTML string into structured data.

    Args:
        html: Raw HTML from the receipt's ``htmlPrintedReceipt`` field.

    Returns:
        ParsedReceipt with items, total, payment method and VAT breakdown.

    Raises:
        ReceiptParseError: If no items are found.
    """
    parser = _ReceiptHTMLParser()
    parser.feed(html)
    if not parser.items:
        msg = "No items found in receipt HTML. This parser supports UK Lidl receipts only."
        raise ReceiptParseError(msg, html)
    total = parser.total
    if total is None:
        total = sum(
            (i.price - sum(d.amount for d in i.discounts) for i in parser.items), Decimal(0)
        )
    return ParsedReceipt(
        items=parser.items,
        total=total,
        payment_method=parser.payment_method,
        vat_breakdown=parser.vat,
    )
