"""Parse UK Lidl HTML receipts into structured data."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from ilidl.exceptions import ReceiptParseError
from ilidl.models import Discount, Item


class ParsedReceipt:
    """Result from HTML receipt parsing."""

    def __init__(
        self,
        items: list[Item],
        total: float,
        payment_method: str | None,
        vat_breakdown: dict[str, tuple[float, float]],
    ) -> None:
        self.items = items
        self.total = total
        self.payment_method = payment_method
        self.vat_breakdown = vat_breakdown


class _ReceiptHTMLParser(HTMLParser):
    """Extract data attributes from Lidl receipt HTML spans."""

    def __init__(self) -> None:
        super().__init__()
        self.articles: list[dict[str, str]] = []
        self.vat_entries: list[dict[str, str]] = []
        self.tender_description: str = ""
        self._in_bold = False
        self._current_bold_text = ""
        self._pending_discount_desc: str = ""

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attr_dict = dict(attrs)
        css_class = attr_dict.get("class", "")

        if tag == "span" and "article" in css_class:
            article: dict[str, str] = {}
            for key, val in attrs:
                if key.startswith("data-") and val is not None:
                    article[key] = val
            if "data-art-description" in article:
                self.articles.append(article)

        if tag == "span" and "css_bold" in css_class:
            self._in_bold = True
            self._current_bold_text = ""

        if tag == "span":
            tender = attr_dict.get("data-tender-description")
            if tender:
                self.tender_description = tender

            if attr_dict.get("data-tax-type") and "data-tax-base-amount" in attr_dict:
                entry = {k: v for k, v in attrs if v is not None}
                self.vat_entries.append(entry)

    def handle_data(self, data: str) -> None:
        if self._in_bold:
            self._current_bold_text += data

    def handle_endtag(self, tag: str) -> None:
        if tag != "span" or not self._in_bold:
            return
        self._in_bold = False
        text = self._current_bold_text.strip()

        if text in ("TOTAL", "TOTAL DISCOUNT"):
            return

        if text.startswith("Price") or text.startswith("Coupon"):
            self._pending_discount_desc = text
            return

        if self._pending_discount_desc:
            match = re.match(r"-?([\d.]+)", text)
            if match and self.articles:
                amount = float(match.group(1))
                last_art = self.articles[-1]
                discounts: list[dict[str, object]] = last_art.setdefault("_discounts", [])
                discounts.append(
                    {
                        "description": self._pending_discount_desc,
                        "amount": amount,
                    }
                )
            self._pending_discount_desc = ""


def _parse_total(html: str) -> float:
    """Extract total from the bold TOTAL line."""
    pattern = (
        r'class="css_bold">TOTAL</span>'
        r".*?"
        r'class="css_bold">([\d.]+)</span>'
    )
    match = re.search(pattern, html, re.DOTALL)
    if match:
        return float(match.group(1))
    msg = "Could not find TOTAL in receipt"
    raise ReceiptParseError(msg, html)


def parse_receipt_html(html: str) -> ParsedReceipt:
    """Parse a UK Lidl receipt HTML string into structured data.

    Args:
        html: Raw HTML from the Lidl Plus API's htmlPrintedReceipt field.

    Returns:
        ParsedReceipt with items, total, payment method, and VAT breakdown.

    Raises:
        ReceiptParseError: If no items are found or the HTML cannot be parsed.
    """
    parser = _ReceiptHTMLParser()
    parser.feed(html)

    if not parser.articles:
        msg = "No items found in receipt HTML"
        raise ReceiptParseError(msg, html)

    seen_ids: set[str] = set()
    items: list[Item] = []

    for art in parser.articles:
        art_id = art.get("data-art-id", "")
        desc = art.get("data-art-description", "")
        key = f"{art_id}:{desc}"
        if key in seen_ids:
            continue
        seen_ids.add(key)

        has_quantity = "data-art-quantity" in art
        quantity = float(art["data-art-quantity"]) if has_quantity else 1.0
        unit_price_raw = float(art.get("data-unit-price", "0"))

        if has_quantity:
            price = round(quantity * unit_price_raw, 2)
            unit_price: float | None = unit_price_raw
        else:
            price = unit_price_raw
            unit_price = None

        discounts = [
            Discount(description=d["description"], amount=d["amount"])
            for d in art.get("_discounts", [])
        ]

        items.append(
            Item(
                name=desc,
                price=price,
                vat_group=art.get("data-tax-type", ""),
                quantity=quantity,
                unit_price=unit_price,
                discounts=discounts,
            )
        )

    total = _parse_total(html)

    vat_breakdown: dict[str, tuple[float, float]] = {}
    for entry in parser.vat_entries:
        tax_type = entry.get("data-tax-type", "")
        base = float(entry.get("data-tax-base-amount", "0"))
        amount = float(entry.get("data-tax-amount", "0"))
        vat_breakdown[tax_type] = (base, amount)

    return ParsedReceipt(
        items=items,
        total=total,
        payment_method=parser.tender_description or None,
        vat_breakdown=vat_breakdown,
    )
