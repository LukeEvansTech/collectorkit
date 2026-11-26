"""Pages. Sign-in is the cluster's job (the route sits behind Pocket ID); /img is served on a
second, open route so a mail client can load photos without a session."""

from __future__ import annotations

import threading
from pathlib import Path

from collectorkit import metrics, runs, scheduler
from collectorkit.db import DB
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import sweep
from .config import Settings
from .db import open_db

HERE = Path(__file__).parent


def create_app(s: Settings, opened: DB | None = None, start_scheduler: bool = False) -> FastAPI:
    db = opened or open_db(s.common.db_path)
    app = FastAPI(title="myapp", docs_url=None, redoc_url=None)
    tpl = Jinja2Templates(directory=HERE / "templates")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        listings = db.all("SELECT * FROM listings ORDER BY first_seen DESC, name LIMIT 200")
        last = db.one("SELECT * FROM runs ORDER BY id DESC LIMIT 1")
        return tpl.TemplateResponse(
            request,
            "home.html",
            {
                "listings": listings,
                "last": last,
                "coverage": runs.coverage(db, last["id"]) if last else [],
                "next_at": scheduler.next_time(s.schedule, s.common.timezone),
                "version": s.common.version,
            },
        )

    @app.post("/sweep")
    def sweep_now():
        threading.Thread(target=sweep.run, args=(db, s, "manual"), daemon=True).start()
        return RedirectResponse("/", status_code=303)

    @app.get("/img/{name}")
    def img(name: str):
        path = s.img_dir / name
        if "/" in name or ".." in name or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg")

    # The alert reads this gauge: a sweep counts only when it read listings and its mail did
    # not fail.
    delivered = runs.DELIVERED + " AND alerts NOT LIKE 'failed%'"
    metrics.mount(
        app,
        "myapp",
        s.common.version,
        lambda: runs.last_success(db, delivered),
        lambda: {"listings": len(db.all("SELECT 1 FROM listings"))},
    )

    if start_scheduler:
        scheduler.start(s.schedule, s.common.timezone, lambda: sweep.run(db, s), "sweep")
        if db.one("SELECT 1 FROM runs LIMIT 1") is None:
            # A fresh volume: take the baseline now, so the last-success gauge is set well
            # before the stale alert's wait runs out, not at the first scheduled time.
            threading.Thread(target=sweep.run, args=(db, s, "first"), daemon=True).start()
    return app
