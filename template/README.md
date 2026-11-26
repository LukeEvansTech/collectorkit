# Starting a new collector app

A working skeleton: it reads its sources, stores listings, mails the new ones with photos and
coverage, and serves a page, `/health` and `/metrics`. Copy it, rename it, then replace the
sources, the schema and the pages with the app's own.

## Steps

1. **Repository.** Create it the estate's way (a pull request to the repository that manages
   GitHub repositories), public or private as its data requires. What you own and what you paid
   belongs in the app's database or a private repository.
2. **Copy** this directory into the new repository and rename `myapp`, `Myapp` and `MYAPP`
   throughout (directory, imports, environment prefix, Dockerfile labels, manifests).
3. **CI.** Keep `.github/workflows/docker-publish.yml`. Copy `lint.yml`, `security-scans.yml`,
   `.github/linters/`, `.github/merge-rows`, `.renovaterc.json5` and `.lefthook.toml` from
   collectorkit itself; add `build-and-push` to `merge-rows` and `dockerfile` to the checkov
   frameworks.
4. **Pin.** Set the collectorkit tag in `requirements.in`, then compile `requirements.txt`
   (`uv pip compile requirements.in -o requirements.txt`).
5. **Sources.** Replace `sources.py`. Look for a feed first (`collect.woo`, `collect.shopify`);
   render a page only when there is none, and give it `href_match` or `img_match`.
6. **Judging.** Rules go in their own pure, tested module. A model call goes through
   `collectorkit.llm_cache.ask` so a re-run does not pay twice.
7. **Tests.** `tests/test_app.py` holds the four behaviours every collector must keep: baseline,
   new listings mailed once, a failed send retried, a failed source not counted.
8. **Cluster.** `deploy/README.md` is the worked example for the home cluster: every manifest
   the app needs, to create under `kubernetes/apps/custom/<app>/`. The alert thresholds follow
   the schedule: a daily sweep alerts after 36 hours.

## Run it

```sh
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python -m myapp sweep --no-notify
python -m myapp serve
```
