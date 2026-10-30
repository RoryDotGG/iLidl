"""CLI for ilidl."""

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import click

from ilidl.auth import BROWSERS, COOKIE_ENV, load_cookies
from ilidl.client import LidlClient
from ilidl.config import Config
from ilidl.exceptions import CouponError, ILidlError
from ilidl.models import Coupon


class _Cli(click.Group):
    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except ILidlError as exc:
            raise click.ClickException(str(exc)) from exc


def _get_client() -> LidlClient:
    config = Config()
    if not config.browser and not os.environ.get(COOKIE_ENV):
        click.echo("Not logged in. Run: ilidl login --browser brave", err=True)
        raise SystemExit(1)
    client = LidlClient(load_cookies(config.browser))
    click.get_current_context().call_on_close(client.close)
    return client


def _json_serial(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    msg = f"Type {type(obj)} not serializable"
    raise TypeError(msg)


def _echo_json(data: Any) -> None:
    click.echo(json.dumps(data, default=_json_serial, indent=2, ensure_ascii=False))


def _coupon_label(c: Coupon) -> str:
    return c.description or f"{c.offer} {c.title}".strip()


@click.group(cls=_Cli)
def cli() -> None:
    """Lidl UK receipts and coupons, using your lidl.co.uk browser session."""


@cli.command()
@click.option(
    "--browser",
    type=click.Choice(sorted(BROWSERS)),
    required=True,
    help="Browser where you are logged in to lidl.co.uk",
)
def login(browser: str) -> None:
    """Check the browser's Lidl session works and remember the browser."""
    with LidlClient(load_cookies(browser)) as client:
        client.check_session()
    config = Config()
    config.browser = browser
    config.save()
    click.echo(f"Logged in using {browser} cookies. Saved to {config.path}")


@cli.command("receipts")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--from", "from_date", type=click.DateTime(["%Y-%m-%d"]), default=None)
@click.option("--to", "to_date", type=click.DateTime(["%Y-%m-%d"]), default=None)
@click.option("--limit", type=click.IntRange(min=1), default=None, help="Stop after N receipts")
def receipts_cmd(
    as_json: bool,
    from_date: datetime | None,
    to_date: datetime | None,
    limit: int | None,
) -> None:
    """List receipts, newest first."""
    client = _get_client()
    found = []
    for r in client.receipts():
        day = r.date.date()
        if from_date and day < from_date.date():
            break  # newest first, so everything after is older
        if to_date and day > to_date.date():
            continue
        found.append(r)
        if limit and len(found) >= limit:
            break

    if as_json:
        _echo_json([asdict(r) for r in found])
        return
    if not found:
        click.echo("No receipts found.")
        return
    click.echo(f"{'Date':<17} {'Store':<20} {'Items':>5} {'Total':>8}  ID")
    click.echo("-" * 80)
    for r in found:
        click.echo(
            f"{r.date:%Y-%m-%d %H:%M} {r.store.name:<20} {r.article_count or 0:>5} "
            f"{r.total:>8.2f}  {r.id}"
        )


@cli.command("receipt")
@click.argument("ticket_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def receipt_cmd(ticket_id: str, as_json: bool) -> None:
    """Show receipt detail. Use 'latest' for the most recent."""
    client = _get_client()
    receipt = client.latest_receipt() if ticket_id == "latest" else client.receipt(ticket_id)

    if as_json:
        _echo_json(asdict(receipt))
        return
    click.echo(f"Receipt: {receipt.id}")
    click.echo(f"Date:    {receipt.date:%Y-%m-%d %H:%M}")
    click.echo(f"Store:   {receipt.store.name}, {receipt.store.locality}")
    click.echo()
    click.echo(f"{'Item':<35} {'Qty':>6} {'Price':>8}")
    click.echo("-" * 51)
    for item in receipt.items:
        qty = "" if item.quantity == 1 else f"{item.quantity.normalize()}"
        click.echo(f"{item.name:<35} {qty:>6} {item.price:>8.2f}")
        for d in item.discounts:
            click.echo(f"  {d.description:<33} {'':>6} {-d.amount:>8.2f}")
    click.echo("-" * 51)
    click.echo(f"{'TOTAL':<35} {'':>6} {receipt.total:>8.2f}")
    if receipt.payment_method:
        click.echo(f"Paid by: {receipt.payment_method}")


@cli.group("coupons")
def coupons_group() -> None:
    """Manage coupons."""


@coupons_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def coupons_list(as_json: bool) -> None:
    """List coupons."""
    all_coupons = _get_client().coupons()
    if as_json:
        _echo_json([asdict(c) for c in all_coupons])
        return
    if not all_coupons:
        click.echo("No coupons available.")
        return
    click.echo(f"{'Coupon':<40} {'Valid until':<12} {'Active':>6}  ID")
    click.echo("-" * 100)
    for c in all_coupons:
        active = "Yes" if c.is_activated else "No"
        click.echo(f"{_coupon_label(c)[:40]:<40} {c.end_date:%Y-%m-%d}   {active:>6}  {c.id}")


def _apply(ids: tuple[str, ...], action: str, change: Any) -> None:
    failed = False
    for coupon_id in ids:
        try:
            change(coupon_id)
            click.echo(f"{action}: {coupon_id}")
        except CouponError as exc:
            click.echo(f"Not {action.lower()}: {coupon_id} ({exc.reason})", err=True)
            failed = True
    if failed:
        raise SystemExit(1)


def _not_activatable(c: Coupon, now: datetime) -> str:
    if c.is_locked:
        return "locked"
    if c.is_processing:
        return "processing"
    if c.start_date > now:
        return f"starts {c.start_date:%Y-%m-%d %H:%M} UTC"
    return ""


@coupons_group.command("activate")
@click.argument("coupon_ids", nargs=-1)
@click.option("--all", "activate_all", is_flag=True, help="Activate every coupon you can now")
def coupons_activate(coupon_ids: tuple[str, ...], activate_all: bool) -> None:
    """Activate coupons by ID, or every inactive coupon with --all."""
    if not coupon_ids and not activate_all:
        click.echo("Provide coupon IDs or use --all", err=True)
        raise SystemExit(1)
    client = _get_client()
    if coupon_ids:
        _apply(coupon_ids, "Activated", client.activate_coupon)
        return

    # Re-list every time: time-slot coupons get a new ID for each slot.
    now = datetime.now(UTC)
    for c in client.coupons():
        if c.is_activated:
            continue
        skip = _not_activatable(c, now)
        if not skip:
            try:
                client.activate_coupon(c.id)
                click.echo(f"Activated: {_coupon_label(c)}")
                continue
            except CouponError as exc:
                skip = exc.reason
        click.echo(f"Skipped: {_coupon_label(c)} ({skip})", err=True)


@coupons_group.command("deactivate")
@click.argument("coupon_ids", nargs=-1, required=True)
def coupons_deactivate(coupon_ids: tuple[str, ...]) -> None:
    """Deactivate coupons by ID."""
    _apply(coupon_ids, "Deactivated", _get_client().deactivate_coupon)
