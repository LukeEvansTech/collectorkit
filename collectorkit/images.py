"""Listing photos: download once and keep a JPEG copy on the volume.

Shop image URLs expire with the listing and some refuse hotlinking, so pages and emails serve
the local copy. Shops also serve PNG or WebP under a ``.jpg`` name; ``as_jpeg`` makes the bytes
match the name before a model or a mail client sees them.
"""

from __future__ import annotations

import hashlib
import io
import logging
import urllib.request
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0 Safari/537.36"
)
MAX_SIDE = 640


def fetch(url: str, referer: str = "", limit: int = 8_000_000) -> bytes:
    if not url.startswith(("https://", "http://")):
        raise ValueError("not an http(s) URL")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer or url})
    with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310: scheme checked above
        return r.read(limit)


def as_jpeg(raw: bytes, max_side: int = 0, quality: int = 85) -> bytes | None:
    """The image as JPEG bytes, shrunk to ``max_side`` when given; None when it is not an image."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        rgb = img.convert("RGB")
        if max_side:
            rgb.thumbnail((max_side, max_side))
        out = io.BytesIO()
        rgb.save(out, "JPEG", quality=quality)
        return out.getvalue()
    except (OSError, ValueError):
        return None


def store(raw: bytes, img_dir: Path, max_side: int = MAX_SIDE) -> str:
    """Save a JPEG copy named by the hash of the original bytes; returns the file name.
    Raises ValueError when the bytes are not an image."""
    jpeg = as_jpeg(raw, max_side)
    if jpeg is None:
        raise ValueError("not an image")
    name = hashlib.sha256(raw).hexdigest()[:24] + ".jpg"
    path = img_dir / name
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(jpeg)
        tmp.replace(path)
    return name


def download(url: str, img_dir: Path, referer: str = "") -> str:
    """The stored file's name, or '' when the photo cannot be fetched: the listing is kept
    either way."""
    if not url:
        return ""
    try:
        return store(fetch(url, referer), img_dir)
    except Exception as e:  # pylint: disable=broad-exception-caught
        log.warning("image %s: %s", url[:120], type(e).__name__)
        return ""
