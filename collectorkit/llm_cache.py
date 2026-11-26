"""Ask a model once per question.

The same prompt about the same photos gets the stored answer, so a re-run or a backfill does
not pay twice. Only an answer is stored: a failed call, or one with no JSON in it, is asked
again next time. Two callers asking the same new question at the same moment both pay; a
collector's sweeps never overlap, so that does not arise. Include ``SCHEMA`` in the app's
schema.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .db import DB
from .llm import LLM
from .runs import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    answer TEXT NOT NULL,
    asked TEXT NOT NULL
);
"""


def key(model: str, prompt: str, photos: list[Path | bytes] | None = None) -> str:
    """A hash of the model, the prompt and the photos' bytes. A changed prompt is a new
    question. Raises OSError when a photo cannot be read."""
    h = hashlib.sha256()
    for part in (model.encode(), prompt.encode()):
        h.update(len(part).to_bytes(8, "big") + part)
    for p in photos or []:
        raw = p if isinstance(p, bytes) else p.read_bytes()
        h.update(len(raw).to_bytes(8, "big") + hashlib.sha256(raw).digest())
    return h.hexdigest()


def ask(
    db: DB,
    model: LLM,
    prompt: str,
    photos: list[Path | bytes] | None = None,
    max_tokens: int = 1500,
) -> dict | None:
    """``model.ask``, answered from the cache when this question has been asked before."""
    try:
        k = key(model.model, prompt, photos)
    except OSError:
        return None  # a photo gone from the volume: no answer, as model.ask would give
    row = db.one("SELECT answer FROM llm_cache WHERE key = ?", k)
    if row:
        return json.loads(row["answer"])
    answer = model.ask(prompt, photos, max_tokens)
    if answer is not None:
        db.run(
            "INSERT OR REPLACE INTO llm_cache (key, model, answer, asked) VALUES (?, ?, ?, ?)",
            k,
            model.model,
            json.dumps(answer),
            now(),
        )
    return answer
