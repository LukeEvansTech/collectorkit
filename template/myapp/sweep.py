"""One sweep: read every source, store what it showed, mail what is new.

The order matters. Listings are marked seen only after the mail that carried them went, so a
failed send leaves them new for the next sweep; a source read for the first time is recorded
at once and announces nothing.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from collectorkit import collect, images, mail, notify, runs, seen
from collectorkit.db import DB
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import sources
from .config import Settings

log = logging.getLogger(__name__)
LOCK = threading.Lock()  # sweeps never overlap
ENV = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)
MAX_PHOTOS = 30


def store(db: DB, items: list[collect.Item]) -> None:
    stamp = runs.now()
    with db.tx() as c:
        c.executemany(
            "INSERT INTO listings (source, key, name, url, price, image, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(source, key) DO UPDATE SET name = excluded.name, url = excluded.url,"
            " price = excluded.price, image = excluded.image, last_seen = excluded.last_seen",
            [(i.source, i.key, i.name, i.url, i.price, i.image, stamp, stamp) for i in items],
        )


def deliver(db: DB, s: Settings, run_id: int, new: list[collect.Item]) -> str:
    """Send the mail and the alert; 'sent', 'off' or 'failed: <reason>'."""
    c = s.common
    if not c.mail_on:
        return "off"
    photos = mail.Photos(domain=c.name, limit=MAX_PHOTOS)
    for i in new[:MAX_PHOTOS]:
        file = images.download(i.image, s.img_dir, referer=i.url)
        if file:
            photos.add(i.image, mail.thumb(s.img_dir / file))
    subject = f"Myapp: {len(new)} new listing{'s' if len(new) != 1 else ''}"
    cover = runs.coverage(db, run_id)
    html = ENV.get_template("mail.html").render(
        new=new, coverage=cover, src=photos.src, link=c.link, title=subject
    )
    text = "\n".join([subject, ""] + [f"{i.name}  {i.price}  {i.url}" for i in new] + [""] + cover)
    result = mail.send(
        c.smtp_host, c.smtp_port, c.mail_from, c.mail_to, subject, html, text, photos, "Myapp"
    )
    if result == "sent":
        pushed = notify.send(c.apprise_urls, subject, new[0].name, c.link("/"), "Open")
        log.info("alert: %s", pushed)
    return result


def run(db: DB, s: Settings, trigger: str = "schedule", notify_on: bool = True) -> int:
    """Run one sweep; returns its run id, or 0 when another sweep is still going."""
    if not LOCK.acquire(blocking=False):
        return 0
    try:
        return _run(db, s, trigger, notify_on)
    finally:
        LOCK.release()


def _run(db: DB, s: Settings, trigger: str, notify_on: bool) -> int:
    run_id = runs.start(db, trigger)
    try:
        new: list[collect.Item] = []
        read: list[collect.Outcome] = []
        for got in collect.run(sources.jobs()):
            if got.items is None:  # a failed read is not an empty one
                runs.source(db, run_id, got.name, error=got.error, seconds=got.seconds)
                continue
            runs.source(db, run_id, got.name, count=len(got.items), seconds=got.seconds)
            store(db, got.items)
            fresh = set(seen.fresh(db, got.name, [i.key for i in got.items]))
            new += [i for i in got.items if i.key in fresh]
            read.append(got)
        result = "nothing new"
        if new:
            result = deliver(db, s, run_id, new) if notify_on else "off"
        for got in read:
            if result in ("sent", "nothing new") or not seen.baselined(db, got.name):
                seen.commit(db, got.name, [i.key for i in got.items if i.key])
        runs.finish(db, run_id, alerts=result)
    except Exception as e:  # pylint: disable=broad-exception-caught
        log.exception("sweep crashed")
        runs.finish(db, run_id, status="failed", error=type(e).__name__)
    return run_id
