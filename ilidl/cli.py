"""CLI for ilidl."""

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

import click
import requests

from ilidl.client import LidlClient
from ilidl.config import Config


def _get_client() -> LidlClient:
    config = Config()
    if not config.refresh_token:
        click.echo("Not logged in. Run: ilidl login", err=True)
        raise SystemExit(1)
    return LidlClient(
        refresh_token=config.refresh_token,
        country=config.country,
        language=config.language,
    )


def _json_serial(obj: Any) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    msg = f"Type {type(obj)} not serializable"
    raise TypeError(msg)


@click.group()
def cli() -> None:
    """Lidl Plus CLI."""


@cli.command()
@click.option("--debug", is_flag=True, help="Save debug screenshots")
def login(*, debug: bool) -> None:
    """Authenticate with Lidl Plus."""
    from ilidl.auth import login as do_login

    config = Config()
    language = click.prompt("Language", default=config.language)
    country = click.prompt("Country", default=config.country)
    config.language = language
    config.country = country
    config.save()

    do_login(config, debug=debug)
    click.echo(f"Logged in. Token saved to {config.path}")


@cli.command("receipts")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option(
    "--from",
    "from_date",
    type=click.DateTime(["%Y-%m-%d"]),
    default=None,
)
@click.option(
    "--to",
    "to_date",
    type=click.DateTime(["%Y-%m-%d"]),
    default=None,
)
def receipts_cmd(
    as_json: bool,
    from_date: datetime | None,
    to_date: datetime | None,
) -> None:
    """List receipts."""
    client = _get_client()
    all_receipts = client.receipts()

    if from_date:
        all_receipts = [r for r in all_receipts if r.date.replace(tzinfo=None) >= from_date]
    if to_date:
        all_receipts = [r for r in all_receipts if r.date.replace(tzinfo=None) <= to_date]

    if as_json:
        click.echo(
            json.dumps(
                [asdict(r) for r in all_receipts],
                default=_json_serial,
                indent=2,
            )
        )
        return

    if not all_receipts:
        click.echo("No receipts found.")
        return

    click.echo(f"{'Date':<20} {'Store':<20} {'Items':>5} {'Total':>8}")
    click.echo("-" * 55)
    for r in all_receipts:
        date_str = r.date.strftime("%Y-%m-%d %H:%M")
        store_name = r.store.name or r.store.id
        click.echo(f"{date_str:<20} {store_name:<20} {len(r.items):>5} {r.total:>7.2f}")


@cli.command("receipt")
@click.argument("ticket_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def receipt_cmd(ticket_id: str, as_json: bool) -> None:
    """Show receipt detail. Use 'latest' for most recent."""
    client = _get_client()

    receipt = client.latest_receipt() if ticket_id == "latest" else client.receipt(ticket_id)

    if as_json:
        click.echo(
            json.dumps(
                asdict(receipt),
                default=_json_serial,
                indent=2,
            )
        )
        return

    click.echo(f"Receipt: {receipt.id}")
    click.echo(f"Date:    {receipt.date.strftime('%Y-%m-%d %H:%M')}")
    click.echo(f"Store:   {receipt.store.name}, {receipt.store.locality}")
    click.echo()
    click.echo(f"{'Item':<35} {'Qty':>5} {'Price':>8}")
    click.echo("-" * 50)
    for item in receipt.items:
        qty = f"{item.quantity:.2f}" if item.quantity != 1.0 else ""
        click.echo(f"{item.name:<35} {qty:>5} {item.price:>7.2f}")
        for d in item.discounts:
            click.echo(f"  {d.description:<33} {'':<5} {-d.amount:>7.2f}")
    click.echo("-" * 50)
    click.echo(f"{'TOTAL':<35} {'':<5} {receipt.total:>7.2f}")
    if receipt.payment_method:
        click.echo(f"Paid by: {receipt.payment_method}")


@cli.group("coupons")
def coupons_group() -> None:
    """Manage coupons."""


@coupons_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def coupons_list(as_json: bool) -> None:
    """List available coupons."""
    client = _get_client()
    all_coupons = client.coupons()

    if as_json:
        click.echo(
            json.dumps(
                [asdict(c) for c in all_coupons],
                default=_json_serial,
                indent=2,
            )
        )
        return

    if not all_coupons:
        click.echo("No coupons available.")
        return

    click.echo(f"{'Title':<30} {'Valid Until':<12} {'Active':>6}")
    click.echo("-" * 50)
    for c in all_coupons:
        end = c.end_date.strftime("%Y-%m-%d")
        active = "Yes" if c.is_activated else "No"
        click.echo(f"{c.title:<30} {end:<12} {active:>6}")


@coupons_group.command("activate")
@click.argument("coupon_id", required=False)
@click.option(
    "--all",
    "activate_all",
    is_flag=True,
    help="Activate all coupons",
)
def coupons_activate(coupon_id: str | None, activate_all: bool) -> None:
    """Activate a coupon."""
    client = _get_client()
    if activate_all:
        for c in client.coupons():
            if not c.is_activated:
                try:
                    client.activate_coupon(c.id)
                    click.echo(f"Activated: {c.title}")
                except requests.HTTPError as e:
                    click.echo(
                        f"Skipped: {c.title} ({e.response.status_code})",
                        err=True,
                    )
        return
    if not coupon_id:
        click.echo("Provide a coupon ID or use --all", err=True)
        raise SystemExit(1)
    client.activate_coupon(coupon_id)
    click.echo("Coupon activated.")


@coupons_group.command("deactivate")
@click.argument("coupon_id")
def coupons_deactivate(coupon_id: str) -> None:
    """Deactivate a coupon."""
    client = _get_client()
    client.deactivate_coupon(coupon_id)
    click.echo("Coupon deactivated.")
