# collectorkit agent guide

Shared library for the collector apps (sleeper, sakuga and the apps built after them).
`README.md` covers the modules and the six rules; this file holds what the code does not say.

- **Extract, never design ahead.** A module arrives here when two apps already carry the same
  code, or one app has it working and the next needs it. An app's schema, sources, prompts,
  pages and its definition of a successful sweep stay in the app.
- **Functions, not a framework.** No base classes for apps to inherit and no registries. An app
  must be able to adopt one module and nothing else.
- **Apps pin a tag.** A change here reaches an app only when that app bumps its pin, in its own
  pull request with its own tests. Breaking a signature needs a new minor version and a line in
  the release notes.
- **Dependencies stay light**: `apprise`, `croniter`, `pillow`; FastAPI only behind the `web`
  extra and imported inside `metrics.mount`. No browser, numpy or OpenCV here.
- Before pushing: `python -m pytest -q`, then black, isort, flake8, pylint, ruff and mypy with
  the configs in `.github/linters/`.

## Review rules

- **Mark sent only after the send succeeded.** Send functions return `"sent"`, `"off"` or
  `"failed: <reason>"` and never raise; nothing here writes a ledger before a send.
- **A failed fetch is not an empty one.** A collector returns its items or raises;
  `collect.run` turns a raise and an empty read into `items=None`. Never return `[]` for a
  failure.
- **A sweep that read nothing is not a success.** `runs.DELIVERED` requires `listings > 0`.
- **The first read is a baseline.** `seen.fresh` is empty until the source's first `commit`.
- **Do not add evasion of bot checks** (stealth patches, captcha solving, challenge bypass). A
  blocked load is a recorded failure.
- **Secrets never reach a log or a return value.** Log the exception type, not its text: URLs
  and messages can carry keys.
