"""Settings from the environment. Every value has a default that works on a laptop.

``Common.load("TOYS")`` reads the settings every collector app has from ``TOYS_*`` variables.
An app keeps its own frozen dataclass for the rest and holds a ``Common`` alongside it.
``APPRISE_URLS`` and ``APP_VERSION`` carry no prefix.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


@dataclass(frozen=True)
class Common:
    name: str
    data_dir: Path
    public_url: str
    timezone: str
    apprise_urls: str
    smtp_host: str
    smtp_port: int
    mail_from: str
    mail_to: str
    llm_url: str
    llm_key: str
    llm_model: str
    version: str

    @classmethod
    def load(cls, prefix: str) -> "Common":
        p = prefix.upper().rstrip("_")
        s = cls(
            name=p.lower(),
            data_dir=Path(env_str(f"{p}_DATA", "data")),
            public_url=env_str(f"{p}_PUBLIC_URL").rstrip("/"),
            timezone=env_str(f"{p}_TZ", "Europe/London"),
            apprise_urls=env_str("APPRISE_URLS"),
            smtp_host=env_str(f"{p}_SMTP_HOST"),
            smtp_port=env_int(f"{p}_SMTP_PORT", 25),
            mail_from=env_str(f"{p}_MAIL_FROM"),
            mail_to=env_str(f"{p}_MAIL_TO"),
            llm_url=env_str(f"{p}_LLM_URL").rstrip("/"),
            llm_key=env_str(f"{p}_LLM_KEY"),
            llm_model=env_str(f"{p}_LLM_MODEL", "claude"),
            version=env_str("APP_VERSION", "0.0.0-dev"),
        )
        s.data_dir.mkdir(parents=True, exist_ok=True)
        return s

    @property
    def db_path(self) -> Path:
        return self.data_dir / f"{self.name}.db"

    @property
    def mail_on(self) -> bool:
        """Email links must be absolute, so the public URL is required too."""
        return bool(
            self.smtp_host
            and self.mail_from
            and self.mail_to
            and self.public_url.startswith(("https://", "http://"))
        )

    def link(self, path: str) -> str:
        return f"{self.public_url}{path}" if self.public_url else path
