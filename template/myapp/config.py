"""Settings from the environment. Every value has a default that works on a laptop."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from collectorkit.config import Common, env_str


@dataclass(frozen=True)
class Settings:
    common: Common
    # One sweep a day; the mail goes out at the end of a sweep that found something new.
    schedule: str

    @property
    def img_dir(self) -> Path:
        return self.common.data_dir / "img"


def load() -> Settings:
    s = Settings(common=Common.load("MYAPP"), schedule=env_str("MYAPP_SCHEDULE", "0 7 * * *"))
    s.img_dir.mkdir(parents=True, exist_ok=True)
    return s
