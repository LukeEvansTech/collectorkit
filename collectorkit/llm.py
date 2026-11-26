"""A client for an OpenAI-compatible chat endpoint (a LiteLLM proxy), with photos.

Standard library only. ``complete`` returns the model's text and ``ask`` the JSON object in it;
both return ``None`` when the call failed, so a caller can tell "no answer" from an answer.
Calls and cost (LiteLLM's ``x-litellm-response-cost`` header) add up on ``usage``. The key never
reaches the log.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Usage:
    calls: int = 0
    cost: float = 0.0


def image_part(photo: Path | bytes) -> dict:
    """A JPEG as a message part. The bytes must be JPEG: a model refuses an image whose bytes
    do not match the declared type (see ``images.as_jpeg``)."""
    raw = photo if isinstance(photo, bytes) else photo.read_bytes()
    data = base64.b64encode(raw).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}


def parse_json(text: str) -> dict | None:
    """The JSON object in a model's answer, or None."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return v if isinstance(v, dict) else None


class LLM:
    def __init__(self, url: str, key: str, model: str, timeout: int = 120):
        self.url, self.key, self.model, self.timeout = url.rstrip("/"), key, model, timeout
        self.usage = Usage()

    @property
    def on(self) -> bool:
        return bool(self.url)

    def complete(
        self, prompt: str, photos: list[Path | bytes] | None = None, max_tokens: int = 1500
    ) -> str | None:
        if not self.url.startswith(("https://", "http://")):
            return None
        try:
            parts = [image_part(p) for p in photos or []]
        except OSError as e:  # a photo that has gone from the volume
            log.warning("llm photo unreadable: %s", type(e).__name__)
            return None
        content = [{"type": "text", "text": prompt}] + parts
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": content}],
            }
        ).encode()
        req = urllib.request.Request(
            f"{self.url}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # nosec B310
                cost = r.headers.get("x-litellm-response-cost", "")
                out = json.loads(r.read())
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.warning("llm call failed: %s", type(e).__name__)
            return None
        self.usage.calls += 1
        try:
            self.usage.cost += float(cost or 0)
        except ValueError:
            pass
        try:
            return out["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return None

    def ask(
        self, prompt: str, photos: list[Path | bytes] | None = None, max_tokens: int = 1500
    ) -> dict | None:
        text = self.complete(prompt, photos, max_tokens)
        return parse_json(text) if text is not None else None
