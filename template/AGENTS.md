# myapp agent guide

Single-user collector of <what>. `README.md` covers what it does and how to run it; this file
holds what the code does not say.

- Pipeline: `myapp/sweep.py` `run()` (sources, store, new since last time, mail and alert, then
  mark seen). Sources: `sources.py`. Pages: `web.py` and `templates/`. The scheduler, storage
  helpers, collectors, mail and metrics come from `collectorkit`; change them there, not here.
- Deployed on the talos-cluster (`kubernetes/apps/custom/myapp`), which alerts on
  `myapp_last_success_timestamp_seconds` from `GET /metrics`. The cluster runs the image of the
  latest `v*` tag: a merge to `main` deploys nothing until a tag is pushed and the pin is bumped.
- Before pushing: `python -m pytest -q`, then black, isort, flake8, pylint, ruff and mypy with
  the configs in `.github/linters/`.

## Review rules

- **Mark sent only after the send succeeded.** `seen.commit` runs after `deliver` returned
  `sent`, and only for what that sweep read.
- **A failed fetch is not an empty one.** A source that failed is recorded in `run_sources` and
  skipped; nothing is retired or marked on a failed read.
- **A sweep that read nothing is not a success.** `/metrics` counts a run only when it read
  listings and its mail did not fail.
- **The first sweep is a baseline.** So is the first read of a source added later. Baseline
  listings are never announced.
- **Do not add evasion of bot checks** (stealth patches, captcha solving). A blocked source is
  recorded as failed and shown in coverage.
- **Every scheduled pipeline alerts on the age of its last success**, not on errors or liveness.
