# collectorkit

The parts my collector apps share. A collector app pulls listings on a schedule, stores what it
saw, judges it with rules and a model, and tells me: a Pushover alert, a daily email with photos,
and web pages. Each app is one Python process (FastAPI and Jinja) with SQLite on a volume.

This is a library of functions, not a framework. An app keeps its own sweep, pages, schema and
rules, and calls these modules for the parts that are the same everywhere.

## Modules

| Module      | What it gives an app                                                                   |
| ----------- | -------------------------------------------------------------------------------------- |
| `scheduler` | One daemon thread per cron expression, correct across clock changes                    |
| `db`        | SQLite in WAL mode, one connection per unit of work, a JSON key-value table            |
| `runs`      | The run ledger: one row per sweep and per source, coverage lines, the last success     |
| `seen`      | Which listings of a source are new; a source's first read is a baseline                |
| `collect`   | WooCommerce and Shopify product feeds, and rendered pages through `obscura`            |
| `llm`       | A client for an OpenAI-compatible endpoint (LiteLLM) with photos, call and cost counts |
| `mail`      | An HTML email with inline photos over an SMTP relay                                    |
| `notify`    | Alerts through Apprise, with a link button on Pushover                                 |
| `metrics`   | `/health`, and `/metrics` with `<app>_last_success_timestamp_seconds`                  |
| `config`    | The settings every app has, read from `<APP>_*` environment variables                  |
| `images`    | Download a photo once and keep a JPEG copy                                             |

## Install

Pin a tag in the app's `requirements.in`:

```text
collectorkit[web] @ git+https://github.com/LukeEvansTech/collectorkit@v0.1.0
```

`[web]` adds FastAPI for `metrics.mount`. Rendered pages need the `obscura` binary on `PATH`, or
its path in `OBSCURA`.

## A whole sweep

```python
from collectorkit import collect, config, mail, metrics, runs, seen
from collectorkit.db import DB

s = config.Common.load("TOYS")
db = DB(s.db_path, runs.SCHEMA + seen.SCHEMA)
runs.mark_interrupted(db)

run_id = runs.start(db)
jobs = [
    ("FavorGK", lambda: collect.woo("https://shop.example")),
    ("Keys", lambda: collect.shopify("https://keys.example")),
]
new, read = [], []
for got in collect.run(jobs):
    if got.items is None:  # a failed read is not an empty one
        runs.source(db, run_id, got.name, error=got.error, seconds=got.seconds)
        continue
    runs.source(db, run_id, got.name, count=len(got.items), seconds=got.seconds)
    keys = set(seen.fresh(db, got.name, [i.key for i in got.items]))
    new += [i for i in got.items if i.key in keys]
    read.append(got)

result = "nothing new"
if new:
    result = "off"  # mail not configured: the listings stay new until it is
    if s.mail_on:
        html, text = render(new, runs.coverage(db, run_id))  # the app's own template
        result = mail.send(
            s.smtp_host, s.smtp_port, s.mail_from, s.mail_to, subject(new), html, text
        )
if result in ("sent", "nothing new"):  # mark seen only after the send succeeded
    for got in read:
        seen.commit(db, got.name, [i.key for i in got.items])
runs.finish(db, run_id, alerts=result)
```

Serve the gauge the cluster alerts on:

```python
metrics.mount(app, "toys", s.version, lambda: runs.last_success(db))
```

## Rules the modules hold to

1. **Mark sent only after the send succeeded.** `mail.send` and `notify.send` return `"sent"`,
   `"off"` or `"failed: …"`; write the ledger on `"sent"` only.
2. **A failed fetch is not an empty one.** `collect.run` gives `items=None` and an error for a
   source that raised or read nothing. Never retire listings on a failed read.
3. **A sweep that read nothing is not a success.** `runs.last_success` counts a run only when it
   read listings.
4. **The first read is a baseline.** `seen.fresh` returns nothing until a source has been
   committed once.
5. **No evasion of bot checks.** A blocked source is recorded as failed and shown in coverage.
6. **Alert on the age of the last success**, not on errors or liveness.

## Develop

```sh
pip install -e '.[web]' -r requirements-dev.txt
python -m pytest -q
```

Lint configs are in `.github/linters/`; `lefthook install` runs them on commit.
