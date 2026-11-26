"""The shops this app reads. Check for a product feed before rendering a page."""

from __future__ import annotations

from typing import Callable

from collectorkit import collect

Job = tuple[str, Callable[[], list[collect.Item]]]


def jobs() -> list[Job]:
    return [
        ("Example Woo shop", lambda: collect.woo("https://shop.example")),
        ("Example Shopify shop", lambda: collect.shopify("https://keys.example")),
        (
            "Example rendered page",
            lambda: collect.page("https://studio.example/new", href_match=r"/products/"),
        ),
    ]
