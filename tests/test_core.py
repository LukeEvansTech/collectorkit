"""scheduler, notify, db, runs, seen, config and metrics."""

# The link helper is tested directly.
# pylint: disable=protected-access

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from collectorkit import config, metrics, notify, runs, scheduler, seen
from collectorkit.db import DB, add_column
from fastapi import FastAPI
from fastapi.testclient import TestClient

SCHEMA = runs.SCHEMA + seen.SCHEMA + "CREATE TABLE IF NOT EXISTS things (id INTEGER PRIMARY KEY);"


@pytest.fixture
def db(tmp_path):
    return DB(tmp_path / "app.db", SCHEMA)


# --- scheduler ---
def test_next_time_follows_the_cron_expression():
    now = dt.datetime(2026, 11, 26, 7, 59, tzinfo=ZoneInfo("Europe/London"))
    assert scheduler.next_time("0 8 * * *", "Europe/London", now).hour == 8


def test_next_time_across_the_autumn_clock_change_is_30_minutes_away():
    # 01:45 BST on the night the clocks go back; the next half hour is 01:00 GMT, which reads
    # earlier on the wall clock. Waiting on timestamps gets the real 15 minutes.
    tz = ZoneInfo("Europe/London")
    now = dt.datetime(2026, 10, 25, 1, 45, tzinfo=tz, fold=0)
    at = scheduler.next_time("*/30 * * * *", "Europe/London", now)
    assert at.timestamp() - now.timestamp() == 15 * 60


def test_next_time_reads_a_reference_time_in_the_schedules_own_zone():
    now = dt.datetime(2026, 7, 1, 7, 30, tzinfo=dt.timezone.utc)  # 08:30 in London
    at = scheduler.next_time("0 8 * * *", "Europe/London", now)
    assert (at.day, at.hour, at.utcoffset()) == (2, 8, dt.timedelta(hours=1))


def test_start_refuses_a_schedule_that_can_never_run():
    for expr, tz in (
        ("not cron", "Europe/London"),
        ("0 8 * * *", "Mars/Olympus"),
        ("0 0 31 2 *", "Europe/London"),
    ):
        with pytest.raises(ValueError):
            scheduler.start(expr, tz, lambda: None)


# --- notify ---
def test_notify_is_off_without_channels():
    assert notify.send("", "t", "b") == "off"


def test_notify_reports_a_rejected_channel_without_echoing_it():
    res = notify.send("nonsense://secret-token", "t", "b")
    assert res.startswith("failed") and "secret-token" not in res


def test_a_rejected_channel_does_not_log_its_credentials(caplog):
    with caplog.at_level("DEBUG"):
        assert notify.send("pover://%20bad-user-key@%20bad-app-token", "t", "b").startswith(
            "failed"
        )
    assert "bad-app-token" not in caplog.text and "bad-user-key" not in caplog.text


def test_pushover_gets_the_link_as_a_button():
    url = notify._with_link("pover://u@t", "https://x.test/a?b=1", "Open")
    assert url.startswith("pover://u@t?") and "url_title=Open" in url
    assert notify._with_link("mailto://x", "https://x.test", "Open") == "mailto://x"


# --- db ---
def test_kv_round_trip_and_default(db):
    assert db.get("missing", 7) == 7
    db.put("k", {"a": [1, 2]})
    db.put("k", {"a": [3]})
    assert db.get("k", None) == {"a": [3]}


def test_tx_rolls_back_on_error(db):
    with pytest.raises(RuntimeError):
        with db.tx() as c:
            c.execute("INSERT INTO things (id) VALUES (1)")
            raise RuntimeError("boom")
    assert db.one("SELECT COUNT(*) n FROM things")["n"] == 0


def test_migrate_adds_a_column_once(tmp_path):
    def migrate(c):
        add_column(c, "things", "colour", "TEXT NOT NULL DEFAULT ''")

    path = tmp_path / "m.db"
    DB(path, SCHEMA, migrate)
    again = DB(path, SCHEMA, migrate)
    again.run("INSERT INTO things (id, colour) VALUES (1, 'red')")
    with again.tx() as c:
        assert add_column(c, "things", "colour", "TEXT") is False
        with pytest.raises(ValueError):
            add_column(c, "things", "x; DROP TABLE things", "TEXT")


# --- runs ---
def test_a_run_with_one_failed_source_is_partial_and_counts_what_was_read(db):
    run_id = runs.start(db, "cli")
    runs.source(db, run_id, "Shop A", count=12, seconds=1.234)
    runs.source(db, run_id, "Shop B", error="RuntimeError: 0 items")
    assert runs.finish(db, run_id) == "partial"
    row = db.one("SELECT * FROM runs WHERE id = ?", run_id)
    assert row["listings"] == 12 and row["trigger"] == "cli" and row["finished"]
    assert runs.coverage(db, run_id) == [
        "Shop A: ok, 12 listings",
        "Shop B: FAILED (RuntimeError: 0 items)",
    ]
    assert runs.last_success(db) > 0


def test_a_run_that_read_nothing_is_not_a_success(db):
    failed = runs.start(db)
    runs.source(db, failed, "Shop A", error="blocked")
    assert runs.finish(db, failed) == "failed"
    empty = runs.start(db)
    assert runs.finish(db, empty) == "failed"
    assert runs.last_success(db) == 0.0


def test_last_success_takes_the_apps_own_definition(db):
    run_id = runs.start(db)
    runs.source(db, run_id, "Shop A", count=3)
    runs.finish(db, run_id, alerts="failed: SMTPException")
    assert runs.last_success(db) > 0
    assert runs.last_success(db, runs.DELIVERED + " AND alerts NOT LIKE 'failed%'") == 0.0
    runs.start(db)  # still running: an OR in the app's condition must not reach it
    assert runs.last_success(db, "alerts = 'sent' OR listings = 0") == 0.0


def test_a_run_cut_off_by_a_restart_is_marked(db):
    run_id = runs.start(db)
    runs.mark_interrupted(db)
    assert db.one("SELECT status FROM runs WHERE id = ?", run_id)["status"] == "interrupted"
    assert runs.last_success(db) == 0.0


# --- seen ---
def test_the_first_read_of_a_source_is_a_baseline(db):
    assert not seen.fresh(db, "shop", ["1", "2"])
    seen.commit(db, "shop", ["1", "2"])
    assert seen.fresh(db, "shop", ["3", "1", "3", "4"]) == ["3", "4"]
    # a second source has its own baseline
    assert not seen.fresh(db, "other", ["3"])


def test_uncommitted_listings_stay_new(db):
    seen.commit(db, "shop", ["1"])
    assert seen.fresh(db, "shop", ["1", "2"]) == ["2"]  # the send failed: no commit
    assert seen.fresh(db, "shop", ["1", "2"]) == ["2"]
    seen.commit(db, "shop", ["1", "2"])
    assert not seen.fresh(db, "shop", ["1", "2"])


# --- config ---
def test_common_reads_the_prefixed_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TOYS_DATA", str(tmp_path / "d"))
    monkeypatch.setenv("TOYS_PUBLIC_URL", "https://toys.example.test/")
    monkeypatch.setenv("TOYS_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("TOYS_MAIL_FROM", "noreply@example.test")
    monkeypatch.setenv("TOYS_SMTP_PORT", " ")
    s = config.Common.load("toys")
    assert s.db_path == tmp_path / "d" / "toys.db" and s.data_dir.is_dir()
    assert s.link("/x") == "https://toys.example.test/x"
    assert s.smtp_port == 25 and s.llm_model == "claude" and s.timezone == "Europe/London"
    assert s.mail_on is False  # no recipient yet
    monkeypatch.setenv("TOYS_MAIL_TO", "me@example.test")
    assert config.Common.load("TOYS").mail_on is True


def test_env_bool(monkeypatch):
    monkeypatch.setenv("X_FLAG", "0")
    assert config.env_bool("X_FLAG", True) is False
    monkeypatch.delenv("X_FLAG")
    assert config.env_bool("X_FLAG", True) is True


# --- metrics ---
def test_render_names_the_gauges_after_the_app():
    text = metrics.render("my-app", 1764172800.4, {"listings": 12})
    assert "my_app_last_success_timestamp_seconds 1764172800\n" in text
    assert "# TYPE my_app_listings gauge\nmy_app_listings 12\n" in text
    with pytest.raises(ValueError):
        metrics.render("", 0)


def test_mount_serves_health_and_metrics():
    app = FastAPI()
    metrics.mount(app, "toys", "1.2.3", lambda: 0.0, lambda: {"sources": 3})
    client = TestClient(app)
    assert client.get("/health").json() == {"ok": True, "version": "1.2.3"}
    body = client.get("/metrics").text
    assert "toys_last_success_timestamp_seconds 0\n" in body and "toys_sources 3\n" in body
