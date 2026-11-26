"""``/health`` and ``/metrics`` for a collector app.

``/health`` says the process is up, which stays true while every sweep fails. The alert that
matters reads ``<app>_last_success_timestamp_seconds`` from ``/metrics``: the finish time of the
last sweep that delivered, by the app's own definition of delivered.
"""

from __future__ import annotations

import re
from typing import Callable, Mapping


def _name(app: str) -> str:
    name = re.sub(r"[^a-z0-9_]", "_", app.lower())
    if not name or name[0].isdigit():
        raise ValueError(f"not a metric prefix: {app!r}")
    return name


def render(
    app: str, last_success: float, gauges: Mapping[str, float] | None = None, what: str = ""
) -> str:
    """Prometheus text: the last-success gauge, then ``<app>_<name>`` for each of ``gauges``."""
    p = _name(app)
    helped = what or "Finish time of the last sweep that delivered."
    lines = [
        f"# HELP {p}_last_success_timestamp_seconds {helped}",
        f"# TYPE {p}_last_success_timestamp_seconds gauge",
        f"{p}_last_success_timestamp_seconds {last_success:.0f}",
    ]
    for key, value in (gauges or {}).items():
        metric = f"{p}_{_name(key)}"
        lines += [f"# TYPE {metric} gauge", f"{metric} {float(value):g}"]
    return "\n".join(lines) + "\n"


def health(version: str) -> dict:
    return {"ok": True, "version": version}


def mount(
    app,
    name: str,
    version: str,
    last_success: Callable[[], float],
    gauges: Callable[[], Mapping[str, float]] | None = None,
    what: str = "",
) -> None:
    """Add ``GET /health`` and ``GET /metrics`` to a FastAPI app."""
    from fastapi.responses import PlainTextResponse  # pylint: disable=import-outside-toplevel

    @app.get("/health")
    def _health() -> dict:
        return health(version)

    @app.get("/metrics", response_class=PlainTextResponse)
    def _metrics() -> str:
        return render(name, last_success(), gauges() if gauges else None, what)
