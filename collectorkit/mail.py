"""An HTML email with inline photos over an SMTP relay.

Photos travel inside the message (CID parts), so they show without the reader's mail client
fetching anything. Build a ``Photos``, add each JPEG under the key the template knows it by,
render the template with ``photos.src``, then ``send``. Mark anything as mailed only when
``send`` returned ``"sent"``.
"""

from __future__ import annotations

import io
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

log = logging.getLogger(__name__)


class Photos:
    """The inline photos of one email."""

    def __init__(self, domain: str = "collector", limit: int = 40):
        self.domain, self.limit = domain, limit
        self.parts: dict[str, tuple[str, bytes]] = {}

    def add(self, key: str, jpeg: bytes | None) -> bool:
        """False when the photo is missing or the email already carries its limit."""
        if not jpeg or not key or (key not in self.parts and len(self.parts) >= self.limit):
            return False
        if key not in self.parts:
            self.parts[key] = (make_msgid(domain=self.domain)[1:-1], jpeg)
        return True

    def src(self, key: str) -> str:
        """The ``src`` for an ``<img>``, or '' (the template then shows the card without one)."""
        return f"cid:{self.parts[key][0]}" if key in self.parts else ""


def thumb(photo: Path | bytes, side: int = 240, quality: int = 80) -> bytes | None:
    """A small JPEG of a photo, or None when it cannot be read."""
    from PIL import Image  # pylint: disable=import-outside-toplevel

    try:
        with Image.open(io.BytesIO(photo) if isinstance(photo, bytes) else photo) as im:
            rgb = im.convert("RGB")
            rgb.thumbnail((side, side))
            out = io.BytesIO()
            rgb.save(out, "JPEG", quality=quality)
            return out.getvalue()
    except (OSError, ValueError):
        return None


def send(
    host: str,
    port: int,
    sender: str,
    to: str,
    subject: str,
    html: str,
    text: str,
    photos: Photos | None = None,
    from_name: str = "",
) -> str:
    """'sent' or 'failed: <reason>'. A recipient the relay refused is a failure, so the whole
    message is tried again next time."""
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr((from_name, sender)) if from_name else sender
        msg["To"] = to
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=sender.rpartition("@")[2] or "collector")
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        body = msg.get_body(("html",))
        for cid, data in (photos.parts if photos else {}).values():
            if isinstance(body, EmailMessage):
                body.add_related(data, "image", "jpeg", cid=f"<{cid}>", disposition="inline")
    except (ValueError, TypeError) as e:  # e.g. a line break in the subject
        log.warning("email could not be built: %s", type(e).__name__)
        return f"failed: {type(e).__name__}"
    try:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.ehlo()
            if smtp.has_extn("starttls"):
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            refused = smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        log.warning("email failed: %s", type(e).__name__)
        return f"failed: {type(e).__name__}"
    if refused:
        return f"failed: {len(refused)} recipient(s) refused"
    return "sent"
