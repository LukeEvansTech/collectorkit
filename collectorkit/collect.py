"""Read listings from shops: product feeds first, a rendered page when there is no feed.

``woo`` reads a WooCommerce Store API feed, ``shopify`` a Shopify ``products.json``; neither
needs a browser. ``page`` renders a listing page with the ``obscura`` command and takes product
cards from its images and links. Each returns the items it read or raises. ``run`` turns a
raise, and an empty read, into a recorded failure: a shop that showed nothing was blocked or
changed its layout, and must not look like a shop with nothing new. A bot challenge is recorded
as a failure and left alone.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import shutil
import subprocess  # nosec B404: fixed argument lists, no shell
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterable

log = logging.getLogger(__name__)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)
# Every image with the link, name and price of the product card around it.
CARDS_JS = """JSON.stringify([...document.querySelectorAll("img")].map(i=>{let a=i.closest("a[href]"),p=i;
for(let n=0;!a&&n<5&&p.parentElement;n++){p=p.parentElement;a=p.querySelector("a[href]")}
const card=(a&&a.closest("li,article,[class*=card],[class*=product]"))||p;
const price=((card.textContent||"").match(/[£$€¥]\\s?[\\d.,]+|[\\d.,]+\\s?€/)||[""])[0];
return [a?a.href:"",(i.alt||i.title||(a&&a.textContent)||"").trim().replace(/\\s+/g," ").slice(0,140),
i.currentSrc||i.src||i.dataset.src||"",price]}).filter(r=>r[0]&&r[1]&&r[2]))"""


class CollectError(RuntimeError):
    """A read that failed for a reason worth showing in coverage. Its text is written by this
    module or the app, so it is safe to store; any other exception is recorded by type alone,
    because its text can carry a URL or a key."""


@dataclass
class Item:
    """One listing as a shop shows it. ``key`` is unique within its source."""

    key: str
    name: str
    url: str
    price: str = ""
    image: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = ""


@dataclass
class Outcome:
    """What one source gave this run: its items, or ``None`` and the error."""

    name: str
    items: list[Item] | None
    error: str | None = None
    seconds: float = 0.0


def http_get(url: str, timeout: int = 40) -> str:
    """The body of a feed URL. curl when the image has it (some shops refuse Python's TLS
    stack and answer curl), else urllib."""
    if not url.startswith(("https://", "http://")):
        raise ValueError("not an http(s) URL")
    if shutil.which("curl"):
        return subprocess.run(  # nosec B603 B607
            ["curl", "-sSfL", "-A", UA, "--connect-timeout", "10", "--max-time", str(timeout), url],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310: scheme checked above
        return resp.read().decode()


def woo_items(products: list[dict]) -> list[Item]:
    out = []
    for p in products:
        pr = p.get("prices") or {}
        minor = int(pr.get("currency_minor_unit") or 0)
        price = (
            f"{pr.get('currency_symbol', '')}{int(pr['price']) / 10**minor:,.2f}"
            if pr.get("price")
            else ""
        )
        labels = (p.get("categories") or []) + (p.get("tags") or [])
        out.append(
            Item(
                key=str(p["id"]),
                name=html.unescape(p["name"]),
                url=p["permalink"],
                price=price,
                image=(p.get("images") or [{}])[0].get("src", ""),
                tags=[html.unescape(c["name"]) for c in labels][:8],
            )
        )
    return out


def woo(base_url: str, pages: int = 2) -> list[Item]:
    """The newest products of a WooCommerce shop. The feed carries no date, so new products
    are found by id."""
    out: list[Item] = []
    for n in range(1, pages + 1):
        url = (
            f"{base_url.rstrip('/')}/wp-json/wc/store/v1/products"
            f"?per_page=50&orderby=date&order=desc&page={n}"
        )
        out += woo_items(json.loads(http_get(url)))
    return out


def shopify_items(data: dict, base_url: str) -> list[Item]:
    out = []
    for p in data.get("products") or []:
        variants = p.get("variants") or [{}]
        tags = p.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        kind = [p["product_type"]] if p.get("product_type") else []
        out.append(
            Item(
                key=str(p["id"]),
                name=p["title"],
                url=f"{base_url.rstrip('/')}/products/{p['handle']}",
                price=str(variants[0].get("price") or ""),
                image=(p.get("images") or [{}])[0].get("src", ""),
                tags=(kind + list(tags))[:8],
            )
        )
    return out


def shopify(base_url: str, limit: int = 250) -> list[Item]:
    """The products of a Shopify shop, newest first as the shop orders them. The price is the
    first variant's, in the shop's own currency and without a symbol."""
    url = f"{base_url.rstrip('/')}/products.json?limit={limit}"
    return shopify_items(json.loads(http_get(url)), base_url)


def page_items(
    rows: Iterable[list[str]],
    href_match: str = "",
    img_match: str = "",
    img_sub: tuple[str, str] | None = None,
    keep_query: bool = False,
) -> list[Item]:
    """Product cards from ``[href, name, image, price]`` rows, one per product link. The key
    is the link without its query string; pass ``keep_query`` for a shop whose products differ
    only there (``/item?itemCode=1``)."""
    out, seen = [], set()
    for href, name, img, price in rows:
        if href_match and not re.search(href_match, href):
            continue
        if img_match and not re.search(img_match, img):
            continue
        if img_sub:  # e.g. a thumbnail path rewritten to the full-size one
            img = re.sub(img_sub[0], img_sub[1], img)
        key = href if keep_query else href.split("?")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(Item(key=key, name=name, url=href, price=price, image=img))
    return out


def page(
    url: str,
    href_match: str = "",
    img_match: str = "",
    img_sub: tuple[str, str] | None = None,
    js: str = CARDS_JS,
    keep_query: bool = False,
) -> list[Item]:
    """Products on a listing page rendered by obscura (``OBSCURA`` names the binary)."""
    binary = os.environ.get("OBSCURA", "obscura")
    r = subprocess.run(  # nosec B603
        [binary, "scrape", url, "-e", js, "-q", "--timeout", "60"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    rows = json.loads(json.loads(r.stdout)["results"][0]["eval"])
    return page_items(rows, href_match, img_match, img_sub, keep_query)


def _reason(e: Exception) -> str:
    if isinstance(e, CollectError):
        return str(e)[:100]
    if isinstance(e, subprocess.CalledProcessError):  # curl: 22 is an HTTP error, 28 a timeout
        return f"{type(e).__name__}: exit {e.returncode}"
    return type(e).__name__


def run(jobs: Iterable[tuple[str, Callable[[], list[Item]]]]) -> list[Outcome]:
    """Run each ``(name, read)`` job. One dead shop does not cost the run."""
    out = []
    for name, read in jobs:
        t0 = time.monotonic()
        try:
            items = read()
            if not items:
                raise CollectError("0 items (blocked, or the page layout changed)")
            for i in items:
                i.source = name
            out.append(Outcome(name, items, None, time.monotonic() - t0))
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.warning("source %s failed: %s", name, type(e).__name__)
            reason = _reason(e)
            out.append(Outcome(name, None, reason, time.monotonic() - t0))
    return out
